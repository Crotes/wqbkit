# 标准库
import logging
from contextlib import contextmanager
from enum import IntEnum
from typing import Any, Generator, List, Optional, Tuple, Union, Dict

from sqlalchemy.orm import Session as SQLAlchemySession
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.dialects.postgresql import insert

from wqbkit.app.database.schemas import FactorData, SimulationData, TaskData

# 本地模块
from wqbkit.app.config import config

from .db_models import (
    AlphaCorr, AlphaFactor, AlphaPnl, AlphaSimulated,
    AlphaTask, get_session_factory, SuperAlpha, FieldCategory
)

# 配置日志
logger = logging.getLogger(__name__)


class Status(IntEnum):
    """状态枚举"""
    PENDING = 0      # 待处理
    PROCESSING = 1   # 处理中
    SUCCESS = 2      # 已完成
    WARNING = 3      # 异常
    FAILED = 4       # 失败


class TaskStatus(IntEnum):
    """任务状态枚举"""
    PENDING = 0          # 待处理
    SIMULATE_FINISH = 1  # 模拟完成
    GENERATE_FINISH = 2  # 生成下一代完成


class AlphaDBManager:
    """Alpha 数据库管理器，提供对各类 Alpha 数据表的增删改查操作。"""

    def __init__(self) -> None:
        """初始化数据库会话工厂，绑定到 SQLAlchemy 引擎。"""
        if not config.ENABLE_DATABASE:
            raise RuntimeError(
                "Database is disabled. Set DB_ENABLE=true in .env to enable DB features."
            )
        self._session_factory = scoped_session(sessionmaker(bind=get_session_factory().bind))
    
    @contextmanager
    def session_scope(self) -> Generator[SQLAlchemySession, None, None]:
        """提供一个事务性的数据库会话，确保在操作完成后自动提交或回滚。"""
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    # -------------------------------------------------------------------------
    # AlphaFactor Table Operations
    # -------------------------------------------------------------------------

    def alphafactor_insert(self, data: FactorData) -> Optional[int]:
        """创建新的 Alpha 因子，发生错误时返回 None"""
        try:
            with self.session_scope() as session:
                # Check for existing alpha
                existing_alpha = session.query(AlphaFactor).filter_by(
                    pre=data.pre,
                    expression=data.expression,
                    region=data.region,
                    universe=data.universe,
                    neutralization=data.neutralization,
                    decay=data.decay,
                    task_id=data.task_id,
                    generation=data.generation
                ).first()
                
                if existing_alpha:
                    return existing_alpha.id
                    
                # Create new alpha
                alpha = AlphaFactor(
                    pre=data.pre,
                    expression=data.expression,
                    region=data.region,
                    universe=data.universe,
                    neutralization=data.neutralization,
                    decay=data.decay,
                    priority=data.priority,
                    task_id=data.task_id,
                    generation=data.generation,
                    tag=data.tag
                )
                session.add(alpha)
                session.flush()  # Flush to get ID
                return alpha.id
        except Exception as e:
            logger.error(f"Failed to insert alpha factor: {e}")
            return None

    def _dedup_factor_data(self, data_list: List[FactorData]) -> List[FactorData]:
        """按表达式+区域+universe+neutralization+decay+task_id+generation 去重。"""
        seen = set()
        result = []

        for data in data_list:
            key = (
                data.expression,
                data.region,
                data.universe,
                data.neutralization,
                data.decay,
                data.task_id,
                data.generation,
            )
            if key not in seen:
                seen.add(key)
                result.append(data)

        return result

    def alphafactor_bulk_insert(self, data_list: List[FactorData]) -> None:
        """批量插入 Alpha 因子，重复则跳过"""
        if not data_list:
            return

        try:
            deduped_list = self._dedup_factor_data(data_list)

            with self.session_scope() as session:
                values = [
                    {
                        "pre": data.pre,
                        "expression": data.expression,
                        "region": data.region,
                        "universe": data.universe,
                        "neutralization": data.neutralization,
                        "decay": data.decay,
                        "priority": data.priority,
                        "status": getattr(data, "status", 0),
                        "task_id": data.task_id,
                        "generation": data.generation,
                        "tag": data.tag,
                    }
                    for data in deduped_list
                ]

                stmt = insert(AlphaFactor).values(values)
                stmt = stmt.on_conflict_do_nothing(
                    constraint="alpha_factors_unique"
                )

                result = session.execute(stmt)

                inserted = result.rowcount or 0
                logger.info(
                    "Alpha factors bulk insert finished. attempted=%s, deduped=%s, inserted=%s, skipped=%s",
                    len(data_list),
                    len(deduped_list),
                    inserted,
                    len(deduped_list) - inserted,
                )

        except Exception:
            logger.exception("Failed to bulk insert alpha factors")
            raise

    def alphafactor_get_by_priority_and_time(self, limit: int = 100) -> List[FactorData]:
        """根据优先级和时间获取 Alpha 因子，并更新状态为处理中"""
        try:
            with self.session_scope() as session:
                # Find the highest priority pending alpha to determine the target region
                first_alpha = session.query(AlphaFactor)\
                    .filter(AlphaFactor.status == Status.PENDING, AlphaFactor.priority != 10)\
                    .order_by(AlphaFactor.priority.asc(), AlphaFactor.task_id.asc(), AlphaFactor.create_time.desc())\
                    .first()

                if not first_alpha:
                    return []

                target_region = first_alpha.region

                alphas = session.query(AlphaFactor)\
                    .filter(AlphaFactor.status == Status.PENDING, AlphaFactor.priority != 10, AlphaFactor.region == target_region)\
                    .order_by(AlphaFactor.priority.asc(), AlphaFactor.task_id.asc(), AlphaFactor.create_time.desc())\
                    .limit(limit)\
                    .with_for_update(skip_locked=True)\
                    .all()
                
                # Update status
                for alpha in alphas:
                    alpha.status = Status.PROCESSING
                
                # Convert to dataclass
                return [FactorData(
                    factor_id=alpha.id,
                    pre=alpha.pre,
                    expression=alpha.expression,
                    neutralization=alpha.neutralization,
                    region=alpha.region,
                    universe=alpha.universe,
                    decay=alpha.decay,
                    task_id=alpha.task_id,
                    priority=alpha.priority,
                    generation=alpha.generation,
                    tag=alpha.tag
                ) for alpha in alphas]
        except Exception as e:
            logger.error(f"Failed to get alpha factors by priority and time: {e}")
            return []

    def alphafactor_update_status(self, id: int, status: int) -> None:
        """更新 Alpha 因子状态"""
        try:
            with self.session_scope() as session:
                session.query(AlphaFactor).filter_by(id=id).update({AlphaFactor.status: status})
        except Exception as e:
            logger.error(f"Failed to update alpha factor status: {e}")

    def alphafactor_bulk_update_status(self, ids: List[int], status: int) -> None:
        """批量更新 Alpha 因子状态"""
        try:
            with self.session_scope() as session:
                session.query(AlphaFactor).filter(AlphaFactor.id.in_(ids)).update(
                    {AlphaFactor.status: status},
                    synchronize_session=False
                )
        except Exception as e:
            logger.error(f"Failed to bulk update alpha factor status: {e}")

    def alphafactor_get_by_status(self, status: int) -> List[AlphaFactor]:
        """根据状态获取 Alpha 因子"""
        try:
            with self.session_scope() as session:
                alphas = session.query(AlphaFactor).filter_by(status=status).all()
                return [FactorData(
                    factor_id=alpha.id,
                    pre=alpha.pre,
                    expression=alpha.expression,
                    neutralization=alpha.neutralization,
                    region=alpha.region,
                    universe=alpha.universe,
                    decay=alpha.decay,
                    task_id=alpha.task_id,
                    priority=alpha.priority,
                    generation=alpha.generation,
                    tag=alpha.tag
                ) for alpha in alphas]
        except Exception as e:
            logger.error(f"Failed to get alpha factors by status: {e}")
            return []

    def alphafactor_get_by_priority(self, priority: int, limit: int = 100) -> List[FactorData]:
        """根据优先级获取 Alpha 因子"""
        try:
            with self.session_scope() as session:
                alphas = session.query(AlphaFactor).filter(
                    AlphaFactor.priority == priority,
                    AlphaFactor.status != Status.SUCCESS,
                ).limit(limit).all()
                return [FactorData(
                    factor_id=alpha.id,
                    pre=alpha.pre,
                    expression=alpha.expression,
                    neutralization=alpha.neutralization,
                    region=alpha.region,
                    universe=alpha.universe,
                    decay=alpha.decay,
                    task_id=alpha.task_id,
                    priority=alpha.priority,
                    generation=alpha.generation,
                    tag=alpha.tag
                ) for alpha in alphas]
        except Exception as e:
            logger.error(f"Failed to get alpha factors by priority: {e}")
            return []

    def alphafactor_get_top_priority(self, limit: int = 100) -> List[AlphaFactor]:
        """获取指定数量的最高优先级 Alpha 因子"""
        try:
            with self.session_scope() as session:
                return session.query(AlphaFactor)\
                    .order_by(AlphaFactor.priority.desc())\
                    .limit(limit)\
                    .all()
        except Exception as e:
            logger.error(f"Failed to get top priority alpha factors: {e}")
            return []
        
    def alphafactor_update_priority(self, id: int, priority: int) -> None:
        """更新 Alpha 因子优先级"""
        try:
            with self.session_scope() as session:
                session.query(AlphaFactor).filter_by(id=id).update({AlphaFactor.priority: priority})
        except Exception as e:
            logger.error(f"Failed to update alpha factor priority: {e}")
    
    def alphafactor_reset_status(self) -> Tuple[bool, str]:
        """重置所有未完成因子的状态"""
        try:
            with self.session_scope() as session:
                session.query(AlphaFactor).filter(AlphaFactor.status != Status.SUCCESS).update(
                    {AlphaFactor.status: Status.PENDING}
                )
            return True, ''
        except Exception as e:
            logger.error(f"Failed to refresh alphas: {e}")
            return False, str(e)
        
    def alphafactor_check_task_completion(self, task_id: int) -> bool:
        """检查任务是否完成（所有因子都已处理完毕）"""
        try:
            with self.session_scope() as session:
                total = session.query(AlphaFactor).filter(AlphaFactor.task_id == task_id).count()
                pending = session.query(AlphaFactor).filter(
                    AlphaFactor.task_id == task_id,
                    AlphaFactor.status != Status.SUCCESS,
                ).count()
                return total != 0 and pending == 0
        except Exception as e:
            logger.error(f"Failed to check task completion: {e}")
            return False

    # -------------------------------------------------------------------------
    # AlphaSimulated Table Operations
    # -------------------------------------------------------------------------

    def alphasimulated_insert(self, data: SimulationData) -> None:
        """插入单条已模拟的 Alpha 记录。"""
        try:
            with self.session_scope() as session:
                alpha = AlphaSimulated(
                    pre=data.pre,
                    expression=data.expression,
                    alpha_id=data.alpha_id,
                    sharpe=data.sharpe,
                    fitness=data.fitness,
                    score=data.score,
                    drawdown=data.drawdown,
                    twoyearsharpe=data.twoyearsharpe,
                    priority=data.priority,
                    neutralization=data.neutralization,
                    region=data.region,
                    universe=data.universe,
                    decay=data.decay,
                    task_id=data.task_id,
                    generation=data.generation,
                    tag=data.tag
                )
                session.add(alpha)
        except Exception as e:
            logger.error(f"Failed to insert simulation result: {e}")

    def alphasimulated_bulk_insert(self, data_list: List[SimulationData]) -> None:
        """批量插入已模拟的 Alpha 记录。"""
        try:
            with self.session_scope() as session:
                alphas = [
                    AlphaSimulated(
                        pre=data.pre,
                        expression=data.expression,
                        alpha_id=data.alpha_id,
                        sharpe=data.sharpe,
                        fitness=data.fitness,
                        score=data.score,
                        drawdown=data.drawdown,
                        twoyearsharpe=data.twoyearsharpe,
                        priority=data.priority,
                        neutralization=data.neutralization,
                        region=data.region,
                        universe=data.universe,
                        decay=data.decay,
                        task_id=data.task_id,
                        generation=data.generation,
                        tag=data.tag
                    ) for data in data_list
                ]
                session.bulk_save_objects(alphas)
        except Exception as e:
            logger.error(f"Failed to bulk insert simulation results: {e}")

    def alphasimulated_delete(self, alpha_id: str) -> None:
        """删除指定 alpha_id 的已模拟 Alpha 记录。"""
        try:
            with self.session_scope() as session:
                session.query(AlphaSimulated).filter_by(alpha_id=alpha_id).delete()
        except Exception as e:
            logger.error(f"Failed to delete simulation result: {e}")

    def alphasimulated_get_by_alpha_id(self, alpha_id: str) -> Optional[SimulationData]:
        """根据 alpha_id 获取已模拟 Alpha 记录。"""
        try:
            with self.session_scope() as session:
                alpha = session.query(AlphaSimulated).filter_by(alpha_id=alpha_id).order_by(AlphaSimulated.id.desc()).first()
                if alpha:
                    return SimulationData(
                        alpha_id=alpha.alpha_id,
                        pre=alpha.pre,
                        expression=alpha.expression,
                        neutralization=alpha.neutralization,
                        region=alpha.region,
                        universe=alpha.universe,
                        decay=alpha.decay,
                        delay=1,
                        sharpe=alpha.sharpe,
                        fitness=alpha.fitness,
                        drawdown=alpha.drawdown,
                        twoyearsharpe=alpha.twoyearsharpe,
                        fail_num=0,
                        priority=alpha.priority,
                        score=alpha.score,
                        task_id=alpha.task_id,
                        generation=alpha.generation,
                        tag=alpha.tag
                    )
                return None
        except Exception as e:
            logger.error(f"Failed to get simulation result by alpha_id: {e}")
            return None

    def alphasimulated_get_by_task_id(self, task_id: int) -> List[SimulationData]:
        """根据任务ID获取已模拟 Alpha 记录，按 score 从大到小排序。"""
        try:
            with self.session_scope() as session:
                alphas = session.query(AlphaSimulated)\
                    .filter_by(task_id=task_id)\
                    .all()
                return [SimulationData(
                    alpha_id=alpha.alpha_id,
                    pre=alpha.pre,
                    expression=alpha.expression,
                    neutralization=alpha.neutralization,
                    region=alpha.region,
                    universe=alpha.universe,
                    decay=alpha.decay,
                    delay=1,
                    sharpe=alpha.sharpe,
                    fitness=alpha.fitness,
                    drawdown=alpha.drawdown,
                    twoyearsharpe=alpha.twoyearsharpe,
                    fail_num=0,
                    priority=alpha.priority,
                    score=alpha.score,
                    task_id=alpha.task_id,
                    generation=alpha.generation,
                    tag=alpha.tag
                ) for alpha in alphas]
        except Exception as e:
            logger.error(f"Failed to get simulation results by task_id: {e}")
            return []
            
    def alphasimulated_update_twoyearsharpe(self, alpha_id: str, twoyearsharpe: float) -> None:
        """更新模拟结果的 twoyearsharpe"""
        try:
            with self.session_scope() as session:
                session.query(AlphaSimulated).filter_by(alpha_id=alpha_id).update({AlphaSimulated.twoyearsharpe: twoyearsharpe})
        except Exception as e:
            logger.error(f"Failed to update simulation twoyearsharpe: {e}")

    # -------------------------------------------------------------------------
    # AlphaTask Table Operations
    # -------------------------------------------------------------------------

    def alphatask_insert(self, data: TaskData) -> Optional[int]:
        """创建新的 Alpha 任务"""
        try:
            with self.session_scope() as session:
                task = AlphaTask(
                    pre=data.pre,
                    name=data.name,
                    region=data.region,
                    universe=data.universe,
                    neutralization=data.neutralization,
                    decay=data.decay,
                    total_alphas=data.total_alphas,
                    parent_task_id=data.parent_task_id,
                    generation=data.generation,
                    priority=data.priority,
                    status=Status.PENDING,
                    simulated_alphas=0,
                    failed_alphas=0,
                    tag=data.tag
                )
                session.add(task)
                session.flush()
                return task.id
        except Exception as e:
            logger.error(f"Failed to insert alpha task: {e}")
            return None

    def alphatask_get_generation(self, task_id: int) -> Optional[int]:
        """根据任务ID获取任务代数"""
        try:
            with self.session_scope() as session:
                result = session.query(AlphaTask.generation).filter_by(id=task_id).first()
                return result[0] if result else None
        except Exception as e:
            logger.error(f"Failed to get alpha task generation: {e}")
            return None

    def alphatask_get_priority(self, task_id: int) -> Optional[int]:
        """根据任务ID获取任务优先级"""
        try:
            with self.session_scope() as session:
                result = session.query(AlphaTask.priority).filter_by(id=task_id).first()
                return result[0] if result else None
        except Exception as e:
            logger.error(f"Failed to get alpha task priority: {e}")
            return None

    def alphatask_increment_success_count(self, task_id: int) -> None:
        """增加任务已模拟的 Alpha 数量"""
        try:
            with self.session_scope() as session:
                session.query(AlphaTask).filter_by(id=task_id).update(
                    {AlphaTask.simulated_alphas: AlphaTask.simulated_alphas + 1},
                    synchronize_session=False
                )
        except Exception as e:
            logger.error(f"Failed to increment task success count: {e}")

    def alphatask_increment_failure_count(self, task_id: int) -> None:
        """增加任务模拟失败的 Alpha 数量"""
        try:
            with self.session_scope() as session:
                session.query(AlphaTask).filter_by(id=task_id).update(
                    {AlphaTask.failed_alphas: AlphaTask.failed_alphas + 1},
                    synchronize_session=False
                )
        except Exception as e:
            logger.error(f"Failed to increment task failure count: {e}")

    def alphatask_get_finished(self) -> Optional[TaskData]:
        """获取已完成模拟的任务"""
        try:
            with self.session_scope() as session:
                tasks = session.query(AlphaTask)\
                    .filter_by(status=TaskStatus.PENDING)\
                    .order_by(AlphaTask.create_time.asc())\
                    .all()
                
                for task in tasks:
                    factors_count = session.query(AlphaFactor).filter_by(task_id=task.id).count()
                    if factors_count == 0:
                        continue
                    
                    simulated_count = session.query(AlphaSimulated).filter_by(task_id=task.id).count()
                    
                    if factors_count > 0 and factors_count == simulated_count:
                        return TaskData(
                            pre=task.pre,
                            name=task.name,
                            region=task.region,
                            universe=task.universe,
                            neutralization=task.neutralization,
                            decay=task.decay,
                            generation=task.generation,
                            priority=task.priority,
                            parent_task_id=task.parent_task_id,
                            total_alphas=task.total_alphas,
                            tag=task.tag,
                            task_id=task.id
                        )
                return None
        except Exception as e:
            logger.error(f"Failed to get finished alpha task: {e}")
            return None

    def alphatask_mark_as_generated(self, task_id: int) -> None:
        """更新任务状态为已生成下一代"""
        try:
            with self.session_scope() as session:
                session.query(AlphaTask).filter_by(id=task_id).update(
                    {AlphaTask.status: TaskStatus.GENERATE_FINISH},
                    synchronize_session=False
                )
        except Exception as e:
            logger.error(f"Failed to mark task as generated: {e}")

    def alphatask_get_by_id(self, task_id: int) -> Optional[TaskData]:
        """根据任务ID获取任务"""
        try:
            with self.session_scope() as session:
                task = session.query(AlphaTask).filter_by(id=task_id).first()
                if task:
                    return TaskData(
                        pre=task.pre,
                        name = task.name,
                        region=task.region,
                        universe=task.universe,
                        neutralization=task.neutralization,
                        decay=task.decay,
                        generation=task.generation,
                        priority=task.priority,
                        parent_task_id=task.parent_task_id,
                        total_alphas=task.total_alphas,
                        tag=task.tag,
                        task_id=task.id
                    )
                return None
        except Exception as e:
            logger.error(f"Failed to get alpha task by id: {e}")
            return None

    # -------------------------------------------------------------------------
    # SuperAlpha Table Operations
    # -------------------------------------------------------------------------

    def superalpha_insert(self, selection_val: str, combo_val: str, alpha_json_val: Any) -> bool:
        """插入新的 SuperAlpha 记录"""
        try:
            with self.session_scope() as session:
                new_alpha = SuperAlpha(
                    selection=selection_val,
                    combo=combo_val,
                    alpha_json=alpha_json_val
                )
                session.add(new_alpha)
            return True
        except Exception as e:
            logger.error(f"Failed to insert super alpha: {e}")
            return False

    def superalpha_get_pending(self) -> Optional[Tuple[int, str, str, Any]]:
        """获取 1 个 status 为 PENDING 的 SuperAlpha 记录"""
        try:
            with self.session_scope() as session:
                alpha = session.query(SuperAlpha).filter_by(status=Status.PENDING).order_by(SuperAlpha.id).with_for_update(skip_locked=True).first()
                if alpha:
                    alpha.status = Status.PROCESSING
                    return (alpha.id, alpha.selection, alpha.combo, alpha.alpha_json)
            return None
        except Exception as e:
            logger.error(f"Failed to get pending super alpha: {e}")
            return None

    def superalpha_update_alpha_id(self, id: int, alpha_id: str) -> Union[bool, None]:
        """更新 SuperAlpha 的 alpha_id"""
        try:
            with self.session_scope() as session:
                session.query(SuperAlpha).filter_by(id=id).update(
                    {'alpha_id': alpha_id},
                    synchronize_session=False
                )
            return True
        except Exception as e:
            logger.error(f"Failed to update super alpha id: {e}")
            return False    
    
    def superalpha_update_status(self, id: int, status: int) -> bool:
        """更新 SuperAlpha 状态"""
        try:
            with self.session_scope() as session:
                session.query(SuperAlpha).filter_by(id=id).update(
                    {'status': status},
                    synchronize_session=False
                )
            return True
        except Exception as e:
            logger.error(f"Failed to update super alpha status: {e}")
            return False

    def superalpha_update_timeuse(self, id: int, timeuse: int) -> bool:
        """更新 SuperAlpha 耗时"""
        try:
            with self.session_scope() as session:
                session.query(SuperAlpha).filter_by(id=id).update(
                    {'timeuse': timeuse},
                    synchronize_session=False
                )
            return True
        except Exception as e:
            logger.error(f"Failed to update super alpha timeuse: {e}")
            return False
    
    def superalpha_update_sharpe_fitness(self, id: int, sharpe: float, fitness: float) -> bool:
        """更新 SuperAlpha 的 Sharpe 和 Fitness"""
        try:
            with self.session_scope() as session:
                session.query(SuperAlpha).filter_by(id=id).update(
                    {'sharpe': sharpe, 'fitness': fitness},
                    synchronize_session=False
                )
            return True
        except Exception as e:
            logger.error(f"Failed to update super alpha sharpe/fitness: {e}")
            return False

    def superalpha_update_correlation(self, id: int, self_corr: float, prod_corr: float) -> bool:
        """更新 SuperAlpha 的相关性"""
        try:
            with self.session_scope() as session:
                session.query(SuperAlpha).filter_by(id=id).update(
                    {'self_corr': self_corr, 'prod_corr': prod_corr},
                    synchronize_session=False
                )
            return True
        except Exception as e:
            logger.error(f"Failed to update super alpha correlation: {e}")
            return False
    
    # -------------------------------------------------------------------------
    # AlphaCorr Table Operations
    # -------------------------------------------------------------------------

    def alphacorr_insert(self, alpha_id: str, self_corr: Optional[float] = None, ppac_corr: Optional[float] = None, prod_corr: Optional[float] = None, self_web_corr: Optional[float] = None) -> bool:
        """插入 Alpha 相关性数据"""
        try:
            with self.session_scope() as session:
                alpha = session.query(AlphaCorr).filter_by(alpha_id=alpha_id).first()
                if alpha:
                    if self_corr is not None: alpha.self_corr = self_corr
                    if ppac_corr is not None: alpha.ppac_corr = ppac_corr
                    if prod_corr is not None: alpha.prod_corr = prod_corr
                    if self_web_corr is not None: alpha.self_web_corr = self_web_corr
                else:
                    new_alpha = AlphaCorr(
                        alpha_id=alpha_id,
                        self_corr=self_corr,
                        ppac_corr=ppac_corr,
                        prod_corr=prod_corr,
                        self_web_corr=self_web_corr
                    )
                    session.add(new_alpha)
            return True
        except Exception as e:
            logger.error(f"Failed to insert alpha correlation: {e}")
            return False
    
    def alphacorr_get(self, alpha_id: str, corr_type: str) -> Tuple[Optional[float], Optional[Any]]:
        """获取 Alpha 相关性数据"""
        try:
            with self.session_scope() as session:
                alpha = session.query(AlphaCorr).filter_by(alpha_id=alpha_id).first()
                if alpha:
                    if corr_type == "self_corr":
                        return alpha.self_corr, None
                    if corr_type == 'ppac_corr':
                        return alpha.ppac_corr, None
                    if corr_type == 'prod_corr':
                        return alpha.prod_corr, alpha.prod_corr_update_time
                    if corr_type == 'self_web_corr':
                        return alpha.self_web_corr, alpha.self_web_corr_update_time
                return None, None
        except Exception as e:
            logger.error(f"Failed to get alpha correlation: {e}")
            return None, None

    # -------------------------------------------------------------------------
    # AlphaPnl Table Operations
    # -------------------------------------------------------------------------

    def alphapnl_get(self, alpha_id: str) -> Optional[str]:
        """获取 Alpha PnL 数据"""
        try:
            with self.session_scope() as session:
                alpha = session.query(AlphaPnl).filter_by(alpha_id=alpha_id).first()
                return alpha.pnl if alpha else None
        except Exception as e:
            logger.error(f"Failed to get alpha pnl: {e}")
            return None

    def alphapnl_bulk_get(self, alpha_ids: List[str]) -> Dict[str, str]:
        """批量获取 Alpha PnL 数据
        
        Args:
            alpha_ids: Alpha ID 列表
            
        Returns:
            Dict[str, str]: alpha_id 到 pnl_data 的映射
        """
        try:
            with self.session_scope() as session:
                alphas = session.query(AlphaPnl).filter(AlphaPnl.alpha_id.in_(alpha_ids)).all()
                return {alpha.alpha_id: alpha.pnl for alpha in alphas}
        except Exception as e:
            logger.error(f"Failed to bulk get alpha pnl: {e}")
            return {}

    def alphapnl_upsert(self, alpha_id: str, alpha_pnl: str) -> bool:
        """插入或更新 Alpha PnL 数据"""
        try:
            with self.session_scope() as session:
                alpha = session.query(AlphaPnl).filter_by(alpha_id=alpha_id).first()
                if alpha is None:
                    new_alpha = AlphaPnl(alpha_id=alpha_id, pnl=alpha_pnl)
                    session.add(new_alpha)
                else:
                    alpha.pnl = alpha_pnl
            return True
        except Exception as e:
            logger.error(f"Failed to upsert alpha pnl: {e}")
            return False

    def alphapnl_bulk_upsert(self, pnl_map: Dict[str, str]) -> bool:
        """批量插入或更新 Alpha PnL 数据"""
        if not pnl_map:
            return True
        try:
            with self.session_scope() as session:
                # 1. 查找已存在的记录
                existing_alphas = session.query(AlphaPnl).filter(
                    AlphaPnl.alpha_id.in_(pnl_map.keys())
                ).all()
                
                existing_ids = {alpha.alpha_id for alpha in existing_alphas}
                
                # 2. 更新已存在的记录
                for alpha in existing_alphas:
                    alpha.pnl = pnl_map[alpha.alpha_id]
                
                # 3. 插入新记录
                new_alphas = [
                    AlphaPnl(alpha_id=aid, pnl=pnl)
                    for aid, pnl in pnl_map.items()
                    if aid not in existing_ids
                ]
                if new_alphas:
                    session.bulk_save_objects(new_alphas)
                    
            return True
        except Exception as e:
            logger.error(f"Failed to bulk upsert alpha pnl: {e}")
            return False

    
    def alphapnl_delete(self, alpha_ids: List[str]) -> bool:
        """删除 Alpha PnL 数据"""
        try:
            with self.session_scope() as session:
                result = session.query(AlphaPnl).filter(AlphaPnl.alpha_id.in_(alpha_ids)).delete(synchronize_session=False)
                logger.info(f"Deleted {result} alpha pnl records")
            return True
        except Exception as e:
            logger.error(f"Failed to delete alpha pnl: {e}")
            return False

    # -------------------------------------------------------------------------
    # FieldCategory Table Operations
    # -------------------------------------------------------------------------

    def field_category_get(self, field: str, region: str) -> Optional[str]:
        """获取字段在特定地区的分类"""
        try:
            with self.session_scope() as session:
                record = session.query(FieldCategory).filter_by(
                    field=field, 
                    region=region
                ).first()
                return record.category if record else None
        except Exception as e:
            logger.error(f"Failed to get field category: {e}")
            return None

    def field_category_upsert(self, field: str, region: str, category: str) -> bool:
        """插入或更新字段分类"""
        try:
            with self.session_scope() as session:
                record = session.query(FieldCategory).filter_by(
                    field=field, 
                    region=region
                ).first()
                
                if record:
                    record.category = category
                else:
                    new_record = FieldCategory(
                        field=field,
                        region=region,
                        category=category
                    )
                    session.add(new_record)
            return True
        except Exception as e:
            logger.error(f"Failed to upsert field category: {e}")
            return False

    def field_category_delete(self, field: str, region: str) -> bool:
        """删除字段在特定地区的分类"""
        try:
            with self.session_scope() as session:
                record = session.query(FieldCategory).filter_by(
                    field=field, 
                    region=region
                ).first()
                if record:
                    session.delete(record)
                return True
        except Exception as e:
            logger.error(f"Failed to delete field category: {e}")
            return False

    def field_category_list(self, region: Optional[str] = None, category: Optional[str] = None) -> List[Dict[str, str]]:
        """获取字段分类列表，可按地区或分类筛选"""
        try:
            with self.session_scope() as session:
                query = session.query(FieldCategory)
                
                if region:
                    query = query.filter_by(region=region)
                if category:
                    query = query.filter_by(category=category)
                    
                records = query.all()
                return [
                    {
                        "field": r.field,
                        "region": r.region,
                        "category": r.category
                    }
                    for r in records
                ]
        except Exception as e:
            logger.error(f"Failed to list field categories: {e}")
            return []

    def field_check(self, field: str) -> bool:
        """检查字段是否存在于 FieldCategory 表中。"""
        try:
            with self.session_scope() as session:
                count = session.query(FieldCategory).filter_by(field=field).count()
                return count != 0
        except Exception as e:
            logger.error(f"Failed to field : {e}")
            return False