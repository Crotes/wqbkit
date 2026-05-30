"""数据库模型定义模块"""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON, Column, DateTime, Float, Integer, String, Text,
    UniqueConstraint, create_engine, text
)
from sqlalchemy.engine import Engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, validates

from wqbkit.app.config import config

# 数据库配置
DB_URI = config.DATABASE_URI

Base = declarative_base()

_engine = None
_Session = None


def get_engine() -> Engine:
    """获取数据库引擎（懒加载）"""
    global _engine
    if _engine is None:
        _engine = create_engine(DB_URI, echo=False)
    return _engine


def get_session_factory() -> sessionmaker:
    """获取会话工厂（懒加载）"""
    global _Session
    if _Session is None:
        _Session = sessionmaker(bind=get_engine())
    return _Session


class AlphaFactor(Base):
    """因子表模型"""
    __tablename__ = 'alpha_factors'
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment="自增主键")
    pre = Column(Text, comment="预处理表达式")
    expression = Column(Text, nullable=False, comment="因子表达式")
    region = Column(String(20), nullable=False, comment="地区（如 USA）")
    universe = Column(String(20), nullable=False, comment="股票池（如 TOP3000）")
    neutralization = Column(String(50), nullable=False, comment="中性化方式（如 SUBINDUSTRY）")
    decay = Column(Integer, nullable=False, comment="衰减周期")
    priority = Column(Integer, default=5, comment="优先级（5最低，0最高）")
    status = Column(Integer, default=0, comment="状态（0:未验证 1:验证中 2:已验证 -1:验证失败）")
    generation = Column(Integer, default=0, comment="任务代数")
    task_id = Column(Integer, comment="所属任务ID")
    tag = Column(Text, comment="Alpha tag")
    create_time = Column(DateTime(timezone=True), server_default=text('CURRENT_TIMESTAMP'), comment="创建时间")
    
    __table_args__ = (
        UniqueConstraint(
            'pre', 'expression', 'region', 'universe', 'neutralization', 'decay', 
            'task_id', 'generation', 
            name='alpha_factors_unique'
        ),
    )

    def __repr__(self) -> str:
        """返回 AlphaFactor 实例的简短描述字符串。"""
        return f"<AlphaFactor(id={self.id}, expression={self.expression[:30]}...)>"


class AlphaSimulated(Base):
    """已模拟的 Alpha 表模型"""
    __tablename__ = 'alpha_simulated'
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment="自增主键")
    pre = Column(Text, comment="预处理表达式")
    expression = Column(Text, comment="Alpha 表达式")
    region = Column(String(20), comment="地区（如 USA）")
    universe = Column(String(20), comment="股票池（如 TOP3000）")
    neutralization = Column(String(50), comment="中性化方式（如 SUBINDUSTRY）")
    decay = Column(Integer, comment="衰减周期")
    priority = Column(Integer, comment="优先级")
    alpha_id = Column(Text, comment="Alpha ID")
    sharpe = Column(Float(53), comment="夏普比率")
    fitness = Column(Float(53), comment="适应度")
    drawdown = Column(Float(53), comment="换手率")
    twoyearsharpe = Column(Float(53), comment="最后两年sharpe")
    score = Column(Float(53), comment="alpha打分")
    task_id = Column(Integer, comment="所属任务ID")
    generation = Column(Integer, default=0, comment="任务代数")
    checked = Column(String, comment="检查状态")
    tag = Column(Text, comment="Alpha tag")

    def __repr__(self) -> str:
        """返回 AlphaSimulated 实例的简短描述字符串。"""
        return f"<AlphaSimulated(id={self.id}, alpha_id={self.alpha_id}, sharpe={self.sharpe})>"


class AlphaTask(Base):
    """Alpha 任务管理表"""
    __tablename__ = 'alpha_tasks'
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment="自增主键")
    name = Column(String(100), comment="任务名称")
    description = Column(Text, comment="任务描述")
    pre = Column(Text, comment="预处理表达式")
    region = Column(String(20), comment="地区（如 USA）")
    universe = Column(String(20), comment="股票池（如 TOP3000）")
    neutralization = Column(String(50), comment="中性化方式（如 SUBINDUSTRY）")
    decay = Column(Integer, comment="衰减周期")
    generation = Column(Integer, default=1, comment="任务代数")
    total_alphas = Column(Integer, default=0, comment="任务包含的 Alpha 总数")
    simulated_alphas = Column(Integer, default=0, comment="已回测的 Alpha 数量")
    selected_alphas = Column(Integer, default=0, comment="筛选后保留的 Alpha 数量")
    failed_alphas = Column(Integer, default=0, comment="模拟失败的 Alpha 数量")
    status = Column(Integer, default=0, comment="任务状态（0:未开始 1:回测中 2:回测完成 3:相关性分析完成 4:已生成下一代）")
    parent_task_id = Column(Integer, comment="父任务ID")
    
    tag = Column(Text, comment="Alpha tag")
    create_time = Column(DateTime(timezone=True), default=datetime.now, comment="创建时间")
    update_time = Column(DateTime(timezone=True), onupdate=datetime.now, comment="更新时间")
    
    priority = Column(Integer, default=5, comment="优先级（5最低，0最高）")

    def __repr__(self) -> str:
        """返回 AlphaTask 实例的简短描述字符串。"""
        return f"<AlphaTask(id={self.id}, name={self.name}, status={self.status})>"


class SuperAlpha(Base):
    """Super Alpha 表模型"""
    __tablename__ = 'superalpha'
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment="自增主键")
    selection = Column(Text, comment="Selection 表达式")
    combo = Column(Text, comment="Combo 表达式")
    alpha_id = Column(String(255), comment="Alpha ID")
    alpha_json = Column(JSON, comment="Alpha JSON 数据")
    status = Column(Integer, default=0, comment="状态（0:未验证 1:验证中 2:已验证 -1:验证失败）")
    timeuse = Column(Integer, default=0, comment="耗时（秒）")
    updatetime = Column(DateTime(timezone=True), onupdate=datetime.now, comment="更新时间")
    sharpe = Column(Float(53), comment="夏普比率")
    fitness = Column(Float(53), comment="适应度")

    def __repr__(self) -> str:
        """返回 SuperAlpha 实例的简短描述字符串。"""
        return f"<SuperAlpha(id={self.id}, alpha_id={self.alpha_id})>"


class AlphaCorr(Base):
    """Alpha Corr 表模型"""
    __tablename__ = 'alpha_corr'

    alpha_id = Column(String(255), primary_key=True, comment="Alpha ID")
    self_corr = Column(Float(53), comment="自相关")
    ppac_corr = Column(Float(53), comment="ppac自相关")
    prod_corr = Column(Float(53), comment="公共相关")
    self_web_corr = Column(Float(53), comment="网页上的自相关")
    prod_corr_update_time = Column(DateTime(timezone=True), comment="公共相关更新时间")
    self_web_corr_update_time = Column(DateTime(timezone=True), comment="网页自相关更新时间")
    
    @validates('prod_corr')
    def update_prod_corr_time(self, key: str, value: Any) -> Any:
        """当 prod_corr 被赋值时，自动更新时间戳"""
        self.prod_corr_update_time = datetime.now(timezone.utc)
        return value
    
    @validates('self_web_corr')
    def update_self_web_corr_time(self, key: str, value: Any) -> Any:
        """当 self_web_corr 被赋值时，自动更新时间戳"""
        self.self_web_corr_update_time = datetime.now(timezone.utc)
        return value


class AlphaPnl(Base):
    """Alpha Pnl 表模型"""
    __tablename__ = 'alpha_pnl'

    alpha_id = Column(String(255), primary_key=True, comment="Alpha ID")
    pnl = Column(Text, comment="Alpha Pnl")


class FieldCategory(Base):
    """字段-地区-分类映射表"""
    __tablename__ = 'field_category'
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment="自增主键")
    field = Column(String(255), nullable=False, comment="字段名")
    region = Column(String(20), nullable=False, comment="地区")
    category = Column(String(50), nullable=False, comment="分类")
    
    __table_args__ = (
        UniqueConstraint('field', 'region', name='uq_field_region'),
    )

    def __repr__(self) -> str:
        """返回 FieldCategory 实例的简短描述字符串。"""
        return f"<FieldCategory(field={self.field}, region={self.region}, category={self.category})>"