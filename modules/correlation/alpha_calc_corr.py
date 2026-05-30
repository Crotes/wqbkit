from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import os
import pickle
from pathlib import Path
from typing import Dict, List, Optional, Union

import numpy as np
import pandas as pd
from tqdm import tqdm

from wqbkit.app.core.alpha_db_core import AlphaDbCore


from wqbkit.app.config import config, DATA_DIR

MAX_WORKERS: int = config.MAX_WORKERS
DEFAULT_CORR_THRESHOLD: float = 0.7
CACHE_VALID_DAYS: int = 7
PICKLE_SUFFIX = ".pickle"
CORR_THRESHOLDS = {
    "ppac": 0.55,
    "self": 0.75,
    "prod": 0.7,
    "self_web": 0.7,
}

class AlphaCalcCorr(AlphaDbCore):
    """Alpha 相关性计算。"""

    def __init__(self) -> None:
        """初始化相关性计算模块，创建本地数据存储目录。"""
        super().__init__()

        self.data_path = (DATA_DIR / "correlation").absolute()
        self.check_path()

        self.alpha_ids, self.ppac_alpha_ids = self.get_active_alphas()
        self.alpha_returns: Optional[pd.DataFrame] = None
        self.alpha_ids_now: Optional[List[str]] = None
        self.region_now: Optional[str] = None
        self.load_data()

    def check_path(self) -> None:
        """若数据缓存目录不存在则创建。"""
        if not os.path.exists(self.data_path):
            os.mkdir(self.data_path)

    @staticmethod
    def save_obj(obj: object, name: str) -> None:
        """将对象序列化为 pickle 文件。"""
        file_path = f"{name}{PICKLE_SUFFIX}"
        with open(file_path, "wb") as file_handle:
            pickle.dump(obj, file_handle, pickle.HIGHEST_PROTOCOL)

    @staticmethod
    def load_obj(name: str) -> object:
        """从 pickle 文件反序列化对象，失败返回 None。"""
        try:
            file_path = f"{name}{PICKLE_SUFFIX}"
            with open(file_path, "rb") as file_handle:
                return pickle.load(file_handle)
        except Exception:
            return None
    

    def load_data(self) -> None:
        """加载所有活跃 Alpha 的收益率数据到内存。"""
        self.alpha_returns = self.get_alpha_results([data["alpha_id"] for data in self.alpha_ids])
    
    
    def get_active_alphas(self) -> tuple[List[Dict[str, str]], List[Dict[str, str]]]:
        """获取当前 OS 阶段的 Alpha 列表，区分普通 Alpha 和 PPAC Alpha，结果缓存到本地。"""
        alpha_ids = self.load_obj(self.data_path / "alpha_ids") or []
        ppac_alpha_ids = self.load_obj(self.data_path / "ppac_alpha_ids") or []

        count = self.wqbs.filter_alphas_limited(others=['stage=OS'], log=None, limit=1, offset=0).json()["count"]
        if count != len(alpha_ids):
            resps = self.wqbs.filter_alphas(
                others=['stage=OS'],
                log=None,
                offset=len(alpha_ids),
                order="dateSubmitted",
            )

            for resp in resps:
                try:
                    data = resp.json()
                    for alpha in data["results"]:
                        alpha_id = alpha["id"]
                        region = alpha["settings"]["region"]
                        ppac_check = any(
                            c.get("name") == "Power Pool Alpha"
                            for c in alpha.get("classifications", [])
                        )

                        info = {
                            "alpha_id": alpha_id,
                            "region": region,
                        }

                        alpha_ids.append(info)
                        if ppac_check:
                            ppac_alpha_ids.append(info)

                except Exception as e:
                    self.logger.error(f"获取 alpha 信息失败: {e}, 状态码 {resp.status_code}")
            self.save_obj(alpha_ids, self.data_path / "alpha_ids")
            self.save_obj(ppac_alpha_ids, self.data_path / "ppac_alpha_ids")

        self.logger.info(f"获取数据成功, {len(alpha_ids)} 个 alpha , {len(ppac_alpha_ids)} 个 ppac")
        
        return alpha_ids, ppac_alpha_ids

    def calc_corr(self, alpha_id: str, calc_type: str, show_detail: bool = False) -> float:
        """计算相关性"""
        if calc_type == "prod":
            return self._get_api_corr(alpha_id, "prod")

        if calc_type == "self_web":
            return self._get_api_corr(alpha_id, "self")

        try:
            region = self._get_alpha_region(alpha_id)
        except Exception as e:
            self.logger.error(f"无法获取Alpha {alpha_id} 的区域信息: {e}")
            return None

        if region != self.region_now:
            self.region_now = region
            self._update_current_alpha_pool(region, calc_type, alpha_id)

        returns_df = self.get_alpha_results(alpha_id)
        if returns_df.empty or alpha_id not in returns_df.columns:
            return None
            
        returns = returns_df[alpha_id]
        
        if self.alpha_returns is None or self.alpha_returns.empty:
            self.logger.warning("基础Alpha池数据为空，无法计算相关性")
            return None
            
        valid_alpha_ids = [aid for aid in self.alpha_ids_now if aid in self.alpha_returns.columns]
        
        if not valid_alpha_ids:
            self.logger.warning(f"区域 {region} 没有匹配的OS Alpha数据")
            return None

        correlations = self.alpha_returns[valid_alpha_ids].corrwith(returns)
        
        if correlations.empty or correlations.isna().all():
            return None
             
        max_corr = correlations.max()
        
        if pd.isna(max_corr):
            return None

        if show_detail:
            self.logger.info(correlations.sort_values(ascending=False).round(4))
            self.logger.info("-------------------------------")
            self.logger.info(self.alpha_returns[valid_alpha_ids].corr().round(4))

        return float(max_corr)

    def _get_api_corr(self, alpha_id: str, corr_type: str) -> float:
        """从API获取相关性"""
        try:
            url = f"https://api.worldquantbrain.com/alphas/{alpha_id}/correlations/{corr_type}"
            return self.get(url).json()["max"]
        except Exception as e:
            self.logger.error(f"获取API相关性失败: {e}")
            return 1.0

    def _get_alpha_region(self, alpha_id: str) -> str:
        """获取Alpha区域信息"""
        resp = self.wqbs.locate_alpha(alpha_id, log=None)
        return resp.json()["settings"]["region"]

    def _update_current_alpha_pool(self, region: str, calc_type: str, exclude_id: str) -> None:
        """更新当前用于计算的Alpha池"""
        if calc_type == "self":
            self.alpha_ids_now = [data["alpha_id"] for data in self.alpha_ids if data["region"] == region]
        else:
            self.alpha_ids_now = [data["alpha_id"] for data in self.ppac_alpha_ids if data["region"] == region]

        self.alpha_ids_now = [aid for aid in self.alpha_ids_now if aid != exclude_id]

    def calculate(self, alpha: Union[str, List[str]], calc_type: str, skip_cache: bool = False, show_detail: bool = False) -> Dict[str, Optional[float]]:
        """批量计算指定 Alpha 与当前池的相关性。"""
        if calc_type not in ["self", "ppac", "prod", "self_web"]:
            self.logger.error(f"不支持的计算类型: {calc_type}")
            return {}

        alpha_ids = [alpha] if isinstance(alpha, str) else alpha
        results: Dict[str, Optional[float]] = {}
        corr_line = CORR_THRESHOLDS.get(calc_type, DEFAULT_CORR_THRESHOLD)

        if not skip_cache:
            results = self._check_cache(alpha_ids, calc_type, corr_line)

        alpha_ids_aft = [a for a in alpha_ids if a not in results]
        self.logger.info(f"预处理后剩余 {len(alpha_ids_aft)} 个alpha")

        if not alpha_ids_aft:
            return results

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_alpha = {
                executor.submit(self.calc_corr, alpha_id, calc_type, show_detail): alpha_id 
                for alpha_id in alpha_ids_aft
            }
            
            finish = 0
            for future in as_completed(future_to_alpha):
                alpha_id = future_to_alpha[future]
                try:
                    corr = future.result()
                    finish += 1
                    self.logger.info(f"{finish}/{len(alpha_ids_aft)} : {alpha_id} - {calc_type}_corr : {corr}")

                    results[alpha_id] = corr
                    
                    if not pd.isna(corr):
                        self._save_to_db(alpha_id, calc_type, corr)
                        
                except Exception as e:
                    self.logger.error(f"计算Alpha {alpha_id} 相关性失败: {e}")
                    results[alpha_id] = None

        return results

    def _check_cache(self, alpha_ids: List[str], calc_type: str, corr_line: float) -> Dict[str, float]:
        """检查数据库缓存"""
        results: Dict[str, float] = {}
        with tqdm(alpha_ids, desc=f"预处理 {calc_type} 相关", mininterval=2, maxinterval=5) as pbar:
            for alpha_id in pbar:
                corr_cache, update_time = self.dbmanager.alphacorr_get(alpha_id, f"{calc_type}_corr")
                if corr_cache is not None and corr_cache != 1:
                    if corr_cache >= corr_line:
                        results[alpha_id] = corr_cache
                    elif calc_type in ["prod", "self_web"]:
                        if update_time and datetime.now() - update_time < timedelta(days=CACHE_VALID_DAYS):
                            results[alpha_id] = corr_cache
        return results

    def _save_to_db(self, alpha_id: str, calc_type: str, corr: float) -> None:
        """保存结果到数据库"""
        try:
            corr_val = round(corr, 4)
            if calc_type == "self":
                self.dbmanager.alphacorr_insert(alpha_id, self_corr=corr_val)
            elif calc_type == "ppac":
                self.dbmanager.alphacorr_insert(alpha_id, ppac_corr=corr_val)
            elif calc_type == "prod":
                self.dbmanager.alphacorr_insert(alpha_id, prod_corr=corr_val)
            elif calc_type == "self_web":
                self.dbmanager.alphacorr_insert(alpha_id, self_web_corr=corr_val)
        except Exception as e:
            self.logger.error(f"保存结果到数据库失败: {e}")
    
    def max_independent_alphas(self, alpha_ids: List[str], correlation_threshold: float = DEFAULT_CORR_THRESHOLD) -> List[str]:
        """寻找最大独立Alpha集合（基于最大团算法）"""
        if not alpha_ids:
            return []

        try:
            alpha_rets = self.get_alpha_results(alpha_ids)
            if alpha_rets.empty:
                return []
            alpha_corr = alpha_rets.corr()
        except KeyError as e:
            self.logger.error(f"部分Alpha ID在基础数据中不存在: {e}")
            return []
            
        edge = alpha_corr < correlation_threshold
        
        n = len(alpha_ids)
        adj_matrix = [[False for _ in range(n)] for _ in range(n)]
        
        for i in range(n):
            for j in range(i + 1, n):
                if edge.iloc[i, j]:
                    adj_matrix[i][j] = True
                    adj_matrix[j][i] = True
        
        max_clique_indices = self._find_max_clique_greedy(adj_matrix)
        max_independent_alpha_ids = [alpha_ids[i] for i in max_clique_indices]
        
        self._print_clique_info(max_independent_alpha_ids, alpha_corr, correlation_threshold)
        
        return max_independent_alpha_ids

    def _find_max_clique_greedy(self, adj_matrix: List[List[bool]]) -> List[int]:
        """使用贪心算法寻找最大团"""
        n = len(adj_matrix)
        if n == 0:
            return []
        
        degrees = [sum(adj_matrix[i]) for i in range(n)]
        
        nodes = list(range(n))
        nodes.sort(key=lambda x: degrees[x], reverse=True)
        
        max_clique = []
        
        for start_node in tqdm(nodes, desc="寻找最大独立集"):
            current_clique = [start_node]
            candidates = [i for i in range(n) if i != start_node and adj_matrix[start_node][i]]
            
            while candidates:
                best_candidate = None
                best_degree = -1
                
                for candidate in candidates:
                    if all(adj_matrix[candidate][node] for node in current_clique):
                        if degrees[candidate] > best_degree:
                            best_candidate = candidate
                            best_degree = degrees[candidate]
                
                if best_candidate is not None:
                    current_clique.append(best_candidate)
                    candidates = [c for c in candidates if c != best_candidate and adj_matrix[best_candidate][c]]
                else:
                    break
            
            if len(current_clique) > len(max_clique):
                max_clique = current_clique
        
        return max_clique

    def _print_clique_info(self, alpha_ids: List[str], corr_matrix: pd.DataFrame, threshold: float):
        """打印最大团结果信息"""
        print("------------------")
        print(f"最大可同时提交的alpha数量: {len(alpha_ids)}")
        print(f"最大团的alpha ID列表: {alpha_ids}")
        
        if len(alpha_ids) > 1:
            selected_corr = corr_matrix.loc[alpha_ids, alpha_ids]
            print("------------------")
            print("选中alpha之间的相关性矩阵:")
            print(selected_corr)
            
            upper_tri = selected_corr.where(np.triu(np.ones(selected_corr.shape), k=1).astype(bool))
            max_corr_in_clique = upper_tri.abs().max().max()
            
            print(f"团内最大相关性: {max_corr_in_clique:.4f} (阈值: {threshold})")
            print(f"验证通过: {max_corr_in_clique < threshold}")

    def calculate_alpha_corr(self, alpha_ids: List[str]) -> None:
        """计算并打印Alpha之间的相关性"""
        returns = self.get_returns(alpha_ids)
        alpha_corr = returns.corr()
        return alpha_corr

    def get_returns(self, alpha_ids: List[str]) -> pd.DataFrame:
        """获取指定 Alpha 列表的收益率矩阵。"""
        pnls = self.get_alpha_pnls(alpha_ids)
        if pnls.empty:
            return pd.DataFrame()
        return self.pnl_to_returns(pnls)
