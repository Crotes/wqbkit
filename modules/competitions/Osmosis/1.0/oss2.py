import logging
import sys
import urllib.parse
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy.stats import rankdata
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.preprocessing import RobustScaler

sys.path.append("/home/worldquant/wqb/Code")
from wqbkit.app.core.alpha_base_core import AlphaBaseCore

logger = logging.getLogger(__name__)

API_BASE_URL = "https://api.worldquantbrain.com"
USERS_SELF_ALPHAS_URL = f"{API_BASE_URL}/users/self/alphas"
ALPHAS_URL = f"{API_BASE_URL}/alphas"
DEFAULT_LIMIT = 50
DEFAULT_OFFSET = 0
DEFAULT_ADVISOR_DATE = datetime(2025, 4, 19)
DEFAULT_TARGET_REGION = "IND"
DEFAULT_ALLOCATION_METHOD = "weighted"
TOTAL_SCORE = 100000
MIN_ASSIGNED_SCORE = 1000
MIN_ALPHA_COUNT = 10
SCORE_BINS = [0, 1000, 2000, 3000, 5000, 10000, float("inf")]
SCORE_BIN_LABELS = ["<1000", "1000-2000", "2000-3000", "3000-5000", "5000-10000", ">10000"]
TURNOVER_IDEAL_CENTER = 14.0
TURNOVER_IDEAL_MIN = 8.0
TURNOVER_IDEAL_MAX = 20.0
TURNOVER_MAX_BUFFER_MULTIPLIER = 4
DEFAULT_WEIGHTS = {
    "fitness": 0.25,
    "returns": 0.20,
    "margin": 0.15,
    "sharpe": 0.20,
    "drawdown": 0.10,
    "turnover": 0.05,
    "balance": 0.05,
}
REQUIRED_COLUMNS = [
    "fitness",
    "returns",
    "margin",
    "sharpe",
    "drawdown",
    "turnover",
    "longCount",
    "shortCount",
]
METHOD_CONFIG = {
    "softmax": {"temperature": 0.1},
    "rank": {"min_score": 100},
    "cluster": {"use_pca": True},
    "weighted": {
        "weights": {"softmax": 0.4, "rank": 0.3, "cluster": 0.3},
        "cluster_weight": 0.3,
    },
}


def get_history_alpha_ids(
    session: AlphaBaseCore,
    region: str,
    start_date: datetime,
    limit: int = DEFAULT_LIMIT,
    offset: int = DEFAULT_OFFSET,
) -> List[Dict[str, float]]:
    """
    从接口分页获取指定地区、指定日期后的alpha数据
    """
    alphas_data = []
    start_date_str = urllib.parse.quote(start_date.astimezone().isoformat(timespec="seconds"))

    while True:
        url = (
            f"{USERS_SELF_ALPHAS_URL}?"
            f"limit={limit}&offset={offset}"
            f"&dateCreated%3E={start_date_str}"
            f"&settings.region={region}"
            f"&status!=UNSUBMITTED%1FIS-FAIL"
            f"&hidden=false"
            f"&type!=SUPER"   # 添加本行，对superalpha进行过滤
            f"&order=-dateSubmitted"
            f"&margin>0.001"
        )

        try:
            resp = session.get(url)
            if resp.status_code != 200:
                logger.error(f"请求出错，状态码：{resp.status_code}")
                break

            data = resp.json()
            results = data.get("results", [])
            alphas_data.extend(results)

            if offset + len(results) >= data.get("count", 0) or len(results) < limit:
                break

            offset += limit
        except Exception as e:
            logger.error(f"数据获取异常: {e}")
            break

    if not alphas_data:
        logger.warning("没有获取到alpha数据")
        return []

    # 提取需要的指标数据
    alpha_metrics = []
    for item in alphas_data:
        is_data = item.get("is", {})
        metrics = {
            "id": item["id"],
            "fitness": is_data.get("fitness", 0.0),
            "longCount": is_data.get("longCount", 0.0),
            "shortCount": is_data.get("shortCount", 0.0),
            "turnover": is_data.get("turnover", 0.0),
            "returns": is_data.get("returns", 0.0),
            "drawdown": is_data.get("drawdown", 0.0),
            "margin": is_data.get("margin", 0.0),
            "sharpe": is_data.get("sharpe", 0.0),
        }

        FAST_D1_check = any(
            classifications.get("name") == "FastD1 Alpha"
            for classifications in item.get("classifications")
        )
        compensated_check = any(
            check.get("name") == "COMPENSATED_ALPHA" and check.get("result") == "WARNING"
            for check in item.get("os").get("checks")
        )
        status_check = item.get("status") == "DECOMMISSIONED"
        if FAST_D1_check or compensated_check or status_check:
            continue  # 跳过不计费alpha和themealpha

        # if metrics['margin'] <= 0.001:
        #     continue  # 跳过margin为0的alpha

        alpha_metrics.append(metrics)

    return alpha_metrics

def calculate_turnover_score(turnover: float) -> float:
    """
    计算turnover得分，理想区间为8-20%
    """
    if pd.isna(turnover):
        return 0.5

    if TURNOVER_IDEAL_MIN <= turnover <= TURNOVER_IDEAL_MAX:
        distance = abs(turnover - TURNOVER_IDEAL_CENTER) / (
            TURNOVER_IDEAL_MAX - TURNOVER_IDEAL_MIN
        )
        score = 1.0 - distance
    elif turnover < TURNOVER_IDEAL_MIN:
        score = max(0, turnover / TURNOVER_IDEAL_MIN)
    else:
        score = (
            max(
                0,
                1.0
                - (turnover - TURNOVER_IDEAL_MAX)
                / (TURNOVER_MAX_BUFFER_MULTIPLIER * TURNOVER_IDEAL_MAX),
            )
            if TURNOVER_IDEAL_MAX > 0
            else 0
        )

    return max(0, min(1, score))

def calculate_balance_score(long_count: float, short_count: float) -> float:
    """
    计算多空平衡得分
    """
    if pd.isna(long_count) or pd.isna(short_count):
        return 0.5

    if long_count == 0 and short_count == 0:
        return 0.0

    if long_count == 0 or short_count == 0:
        return 0.2

    ratio = (
        min(long_count, short_count) / max(long_count, short_count)
        if max(long_count, short_count) > 0
        else 0
    )
    balance_score = ratio ** 0.5 if ratio >= 0 else 0

    return min(1, max(0, balance_score))

def calculate_alpha_scores(
    alpha_metrics: List[Dict[str, float]],
    weights: Optional[Dict[str, float]] = None,
) -> pd.DataFrame:
    """
    为每个alpha计算综合得分
    """
    if not alpha_metrics:
        logger.warning("没有alpha数据用于计算得分")
        return pd.DataFrame()

    df = pd.DataFrame(alpha_metrics)

    # 检查必要的列是否存在
    missing_columns = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_columns:
        logger.warning(f"缺失列: {missing_columns}，使用默认值填充")
        for col in missing_columns:
            df[col] = 0.0

    if weights is None:
        weights = DEFAULT_WEIGHTS

    for col in ["fitness", "returns", "margin", "sharpe"]:
        if len(df) > 1 and df[col].nunique() > 1:
            df[f'{col}_score'] = rankdata(df[col].fillna(0)) / len(df)
        else:
            df[f'{col}_score'] = 0.5

    # 处理drawdown(越小越好)
    if 'drawdown' in df.columns and len(df) > 1 and df['drawdown'].nunique() > 1:
        neg_drawdown = -df['drawdown'].fillna(df['drawdown'].max() if df['drawdown'].max() > 0 else 1)
        df['drawdown_score'] = rankdata(neg_drawdown) / len(df)
    else:
        df['drawdown_score'] = 0.5

    # 处理turnover
    df['turnover_score'] = df['turnover'].apply(lambda x: calculate_turnover_score(x))

    # 计算多空平衡得分
    df['balance_score'] = df.apply(lambda row: calculate_balance_score(row['longCount'], row['shortCount']), axis=1)

    # 计算综合得分
    df['composite_score'] = (
        weights['fitness'] * df['fitness_score'] +
        weights['returns'] * df['returns_score'] +
        weights['margin'] * df['margin_score'] +
        weights['sharpe'] * df['sharpe_score'] +
        weights['drawdown'] * df['drawdown_score'] +
        weights['turnover'] * df['turnover_score'] +
        weights['balance'] * df['balance_score']
    )

    # 归一化到[0,1]
    if len(df) > 1 and df['composite_score'].nunique() > 1:
        score_min = df['composite_score'].min()
        score_max = df['composite_score'].max()
        if score_max > score_min:
            df['composite_score'] = (df['composite_score'] - score_min) / (score_max - score_min)
        else:
            df['composite_score'] = 0.5
    else:
        df['composite_score'] = 0.5

    return df

def assign_scores_with_softmax(df, total_score=100000, temperature=0.1):
    """
    使用softmax函数分配分数
    """
    if len(df) == 0:
        return df

    # 防止温度参数为0
    temperature = max(temperature, 1e-10)

    # 使用softmax计算概率分布
    scores = df['composite_score'].values
    exp_scores = np.exp(scores / temperature)
    probabilities = exp_scores / exp_scores.sum()

    # 分配分数
    df['assigned_score'] = np.floor(probabilities * total_score).astype(int)

    # 处理四舍五入偏差
    score_diff = total_score - df['assigned_score'].sum()
    if score_diff > 0:
        top_indices = df.nlargest(min(score_diff, len(df)), 'composite_score').index
        df.loc[top_indices, 'assigned_score'] += 1
    elif score_diff < 0:
        bottom_indices = df.nsmallest(min(abs(score_diff), len(df)), 'composite_score').index
        for idx in bottom_indices:
            if df.at[idx, 'assigned_score'] > 1:
                df.at[idx, 'assigned_score'] -= 1
                score_diff += 1
                if score_diff == 0:
                    break

    return df

def assign_scores_with_rank_based(df, total_score=100000, min_score=100):
    """
    基于排名的分数分配方法
    """
    if len(df) == 0:
        return df

    n = len(df)
    min_score = max(1, min_score)  # 确保最小分数为正

    # 计算基础分配
    base_allocation = min_score * n
    if base_allocation > total_score:
        # 如果基础分数总和超过总分，按比例缩减
        scale_factor = total_score / base_allocation
        df['assigned_score'] = (min_score * scale_factor).astype(int)
        return df

    # 分配剩余分数
    remaining_score = total_score - base_allocation
    ranks = rankdata(df['composite_score'])

    # 使用指数权重
    weights = np.exp(ranks / n)
    normalized_weights = weights / weights.sum()
    bonus_scores = np.floor(normalized_weights * remaining_score).astype(int)

    # 分配分数
    df['assigned_score'] = min_score + bonus_scores

    # 调整总分
    score_diff = total_score - df['assigned_score'].sum()
    if score_diff != 0:
        # 将偏差加到最高得分的alpha
        top_idx = df['composite_score'].idxmax()
        df.at[top_idx, 'assigned_score'] += score_diff

    return df

def assign_scores_with_cluster_weighting(df, use_pca=True, total_score=100000):
    """
    结合聚类和综合得分的分数分配方法
    """
    if len(df) < 2:
        df['assigned_score'] = total_score
        return df

    # 检查聚类特征列
    feature_cols = ['returns', 'margin', 'sharpe', 'drawdown', 'turnover']
    available_features = [col for col in feature_cols if col in df.columns]

    if len(available_features) < 2:
        logging.warning("聚类特征不足，使用softmax方法")
        return assign_scores_with_softmax(df, total_score)

    # 准备特征数据
    X = df[available_features].fillna(0).values

    try:
        scaler = RobustScaler()
        X_scaled = scaler.fit_transform(X)

        if use_pca and len(available_features) > 2:
            pca = PCA(n_components=min(0.95, len(available_features)), random_state=42)
            X_processed = pca.fit_transform(X_scaled)
        else:
            X_processed = X_scaled

        # 确定聚类数
        n_samples = len(df)
        n_clusters = min(20, max(2, n_samples // 5))  # 每5个样本一个聚类
        n_clusters = min(n_clusters, n_samples)

        if n_clusters < 2:
            df['cluster'] = 0
        else:
            kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
            df['cluster'] = kmeans.fit_predict(X_processed)

    except Exception as e:
        logging.warning(f"聚类失败: {e}，使用softmax方法")
        return assign_scores_with_softmax(df, total_score)

    # 为每个聚类分配基础分数
    cluster_sizes = df['cluster'].value_counts()
    cluster_base_scores = (cluster_sizes / len(df) * total_score * 0.3).astype(int)

    # 在每个聚类内分配分数
    df['assigned_score'] = 0

    for cluster_id, size in cluster_sizes.items():
        cluster_mask = df['cluster'] == cluster_id
        cluster_df = df[cluster_mask].copy()

        if len(cluster_df) == 0:
            continue

        # 聚类基础分数
        base_for_cluster = cluster_base_scores.get(cluster_id, 0)

        if base_for_cluster > 0:
            # 在聚类内按综合得分分配基础分数
            cluster_scores = cluster_df['composite_score'].values
            if cluster_scores.sum() > 0:
                base_weights = cluster_scores / cluster_scores.sum()
            else:
                base_weights = np.ones(len(cluster_df)) / len(cluster_df)

            base_allocations = np.floor(base_weights * base_for_cluster).astype(int)

            # 处理余数
            remainder = base_for_cluster - base_allocations.sum()
            if remainder > 0:
                top_indices = cluster_df.nlargest(remainder, 'composite_score').index
                base_allocations[cluster_df.index.isin(top_indices)] += 1

            cluster_df['assigned_score'] = base_allocations

        # 更新主DataFrame
        df.loc[cluster_mask, 'assigned_score'] = cluster_df['assigned_score'].values

    # 按综合得分分配剩余分数
    total_assigned = df['assigned_score'].sum()
    remaining_total = total_score - total_assigned

    if remaining_total > 0:
        scores = df['composite_score'].values
        if scores.sum() > 0:
            weights = scores / scores.sum()
        else:
            weights = np.ones(len(df)) / len(df)

        bonus_allocations = np.floor(weights * remaining_total).astype(int)
        df['assigned_score'] += bonus_allocations

        # 处理余数
        total_assigned = df['assigned_score'].sum()
        remaining_total = total_score - total_assigned

        if remaining_total > 0:
            top_indices = df.nlargest(remaining_total, 'composite_score').index
            df.loc[top_indices, 'assigned_score'] += 1

    return df

def assign_scores_weighted_combination(df, total_score=100000,
                                       weights=None, cluster_weight=0.3,
                                       softmax_temp=0.1, min_base_score=50):
    """
    加权组合分配方法
    """
    if len(df) == 0:
        return df

    if weights is None:
        weights = {'softmax': 0.4, 'rank': 0.3, 'cluster': 0.3}

    # 计算各种方法的分数
    df_softmax = assign_scores_with_softmax(df.copy(), total_score, softmax_temp)
    df_rank = assign_scores_with_rank_based(df.copy(), total_score, min_base_score)

    # 计算加权分数
    weighted_scores = (
        weights['softmax'] * df_softmax['assigned_score'] +
        weights['rank'] * df_rank['assigned_score']
    )

    # 添加聚类调整
    if cluster_weight > 0 and len(df) > 1:
        try:
            feature_cols = ['returns', 'margin', 'sharpe', 'drawdown', 'turnover']
            available_features = [col for col in feature_cols if col in df.columns]

            if len(available_features) >= 2:
                X = df[available_features].fillna(0).values
                scaler = RobustScaler()
                X_scaled = scaler.fit_transform(X)

                n_clusters = min(20, max(2, len(df) // 5))

                if n_clusters > 1:
                    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
                    clusters = kmeans.fit_predict(X_scaled)

                    # 计算聚类调整因子
                    for i in range(n_clusters):
                        cluster_mask = clusters == i
                        cluster_size = np.sum(cluster_mask)

                        if cluster_size > 0:
                            cluster_factor = 1.0 / np.sqrt(cluster_size)
                            weighted_scores[cluster_mask] *= (1 + cluster_weight * cluster_factor)

        except Exception as e:
            logging.warning(f"聚类调整失败: {e}")

    # 归一化到总分
    total_weighted = weighted_scores.sum()

    if total_weighted > 0:
        df['assigned_score'] = (weighted_scores / total_weighted * total_score).astype(int)
    else:
        df['assigned_score'] = (total_score // len(df))

    # 调整总分
    total_assigned = df['assigned_score'].sum()
    diff = total_score - total_assigned

    if diff != 0:
        sorted_indices = df.sort_values('composite_score', ascending=False).index
        adjust_count = min(abs(diff), len(df))

        for i in range(adjust_count):
            idx = sorted_indices[i]
            if diff > 0:
                df.at[idx, 'assigned_score'] += 1
            else:
                df.at[idx, 'assigned_score'] = max(1, df.at[idx, 'assigned_score'] - 1)

    return df

def assign_scores_hybrid(df, method='softmax', total_score=100000, **kwargs):
    """
    混合分配方法
    """
    if method == 'softmax':
        temperature = kwargs.get('temperature', 0.1)
        return assign_scores_with_softmax(df, total_score, temperature)
    elif method == 'rank':
        min_score = kwargs.get('min_score', 100)
        return assign_scores_with_rank_based(df, total_score, min_score)
    elif method == 'cluster':
        use_pca = kwargs.get('use_pca', True)
        return assign_scores_with_cluster_weighting(df, use_pca, total_score)
    elif method == 'weighted':
        return assign_scores_weighted_combination(df, total_score, **kwargs)
    else:
        raise ValueError(f"未知的分配方法: {method}")

'''

四种分配方法，概括如下：

Softmax分配法：基于综合得分的指数概率分布，高分Alpha获得指数级更多分数，适合突出表现优异的Alpha。

Rank分配法：基于排名进行指数衰减分配，保证每个Alpha都有基础分数，公平性强，适合追求稳健和公平性的场景。

Cluster加权法：先聚类再分配，确保不同类型Alpha都能获得分数，鼓励策略多样性，适合希望覆盖多种策略的场景。

Weighted混合法：多种方法的加权组合，灵活平衡各方法优点，适合需要综合考量多种因素的场景。

'''

def main():
    advisor_date = DEFAULT_ADVISOR_DATE
    page_limit = DEFAULT_LIMIT
    page_offset = DEFAULT_OFFSET
    target_region = DEFAULT_TARGET_REGION
    allocation_method = DEFAULT_ALLOCATION_METHOD

    # 初始化登录会话
    try:
        session = AlphaBaseCore()
        logger.info("登录成功，开始获取alpha数据")
    except Exception as e:
        logger.error(f"登录失败: {e}")
        return

    '''
    注意：
    这里是获取成为顾问后所配置target_region中所有alpha数据
    后续你需要根据自己的理解需求建立自己独特优异的分配池进行打分
    '''

    # 获取成为顾问后所配置地区所有alpha数据
    alpha_metrics_list = get_history_alpha_ids(
        session=session,
        region=target_region,
        start_date=advisor_date,
        limit=page_limit,
        offset=page_offset
    )

    if not alpha_metrics_list:
        logger.error("未获取到有效alpha数据")
        return

    logger.info(f"共获取到 {len(alpha_metrics_list)} 个alpha")

    num = 0
    
    while True:
        num += 1
        logger.info(f"第 {num} 轮分数分配尝试")
        logger.info(f"共获取到 {len(alpha_metrics_list)} 个alpha")
        last_len = len(alpha_metrics_list)
        # 计算综合得分
        df_scores = calculate_alpha_scores(alpha_metrics_list)
        if df_scores.empty:
            logger.error("无法计算alpha综合得分")
            return

        # 分配分数
        logger.info(f"使用 {allocation_method} 方法进行分数分配...")
        try:
            df_with_scores = assign_scores_hybrid(
                df_scores,
                method=allocation_method,
                total_score=TOTAL_SCORE,
                **METHOD_CONFIG.get(allocation_method, {})
            )
        except Exception as e:
            logger.error(f"分数分配失败: {e}")
            return

        logger.info("=" * 60)
        logger.info(f"最终分配结果（使用{allocation_method}方法）")
        logger.info("=" * 60)

        total_assigned = 0
        successful_updates = 0
        failed_updates = 0

        # 按分配分数排序
        df_with_scores = df_with_scores.sort_values('assigned_score', ascending=False)

        alpha_ids = []
        for idx, alpha in df_with_scores.iterrows():
            if alpha['assigned_score'] <= MIN_ASSIGNED_SCORE:
                continue
            alpha_ids.append(alpha['id'])
        if len(alpha_ids) < MIN_ALPHA_COUNT or len(alpha_ids) == last_len:
            break
        else:
            alpha_metrics_list_tmp = [item for item in alpha_metrics_list if item['id'] in alpha_ids]
            alpha_metrics_list = alpha_metrics_list_tmp

    # 输出每个Alpha的分配结果
    for idx, alpha in df_with_scores.iterrows():
        logger.info(f"Alpha ID: {alpha['id']}")
        logger.info(
            f"  综合得分: {alpha['composite_score']:.4f} (排名: {idx+1}/{len(df_with_scores)})"
        )
        logger.info(f"  分配分数: {alpha['assigned_score']}")

        # 调用API更新分数
        update_url = f"{ALPHAS_URL}/{alpha['id']}"
        try:
            response = session.patch(update_url, json={"osmosisPoints": int(alpha['assigned_score'])})
            if response.status_code == 200:
                successful_updates += 1
                logger.info("  ✓ 分数更新成功")
            else:
                failed_updates += 1
                logger.error(f"  ✗ 分数更新失败: {response.status_code}")
        except Exception as e:
            failed_updates += 1
            logger.error(f"  ✗ 更新异常: {str(e)}")
        total_assigned += alpha['assigned_score']

    # 统计信息
    logger.info("=" * 60)
    logger.info("分配统计")
    logger.info("=" * 60)
    logger.info(f"总alpha数量: {len(df_with_scores)}")
    logger.info(f"总分配分数: {total_assigned}")
    logger.info(f"平均分数: {total_assigned/len(df_with_scores):.0f}")
    logger.info(f"最高分数: {df_with_scores['assigned_score'].max()}")
    logger.info(f"最低分数: {df_with_scores['assigned_score'].min()}")
    logger.info(f"中位数分数: {df_with_scores['assigned_score'].median():.0f}")
    logger.info(f"分数标准差: {df_with_scores['assigned_score'].std():.0f}")

    if df_with_scores['assigned_score'].mean() > 0:
        cv = df_with_scores['assigned_score'].std() / df_with_scores['assigned_score'].mean()
        logger.info(f"变异系数: {cv:.3f}")

    logger.info(f"API更新成功: {successful_updates} 个")
    logger.info(f"API更新失败: {failed_updates} 个")

    # 分数分布
    logger.info("=" * 60)
    logger.info("分数分布")
    logger.info("=" * 60)

    df_with_scores['score_bin'] = pd.cut(
        df_with_scores['assigned_score'],
        bins=SCORE_BINS,
        labels=SCORE_BIN_LABELS,
    )
    bin_counts = df_with_scores['score_bin'].value_counts().sort_index()

    for bin_label, count in bin_counts.items():
        percentage = count/len(df_with_scores)*100
        bar_length = int(percentage/2)
        bar = '█' * bar_length if bar_length > 0 else ''
        logger.info(f"{bin_label}: {count:3d}个alpha ({percentage:5.1f}%) {bar}")

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    main()
