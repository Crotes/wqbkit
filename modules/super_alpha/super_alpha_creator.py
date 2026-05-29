from itertools import product
from typing import Any, Dict, List
from wqbkit.app.database import AlphaDBManager


DEFAULT_DELAY = 1
DEFAULT_TRUNCATION = 0.01
SELECTION_LIMITS = [65, 80]
DECAY_OPTIONS = [6, 12, 18]
COLORS_TO_ASSIGN = ["NONE", "RED", "YELLOW", "GREEN", "BLUE", "PURPLE"]
NEUTRALIZATIONS = [
    "MARKET",
    "SECTOR",
    "INDUSTRY",
    "STATISTICAL",
    "SUBINDUSTRY",
    "CROWDING",
    "FAST",
    "SLOW",
    "REVERSION_AND_MOMENTUM",
    "SLOW_AND_FAST",
]
DATACATEGORIES = [
    "analyst",
    "broker",
    "earnings",
    "fundamental",
    "imbalance",
    "insiders",
    "institutions",
    "macro",
    "model",
    "news",
    "option",
    "other",
    "pv",
    "risk",
    "sentiment",
    "shortinterest",
    "socialmedia",
]
REGIONS = {
    "USA": ["TOP3000"],
    "GLB": ["TOP3000", "MINVOL1M"],
    "EUR": ["TOP2500"],
    "ASI": ["MINVOL1M", "ILLIQUID_MINVOL1M"],
    "CHN": ["TOP2000U"],
}


class SuperAlphaCreator:
    def __init__(self, region: str) -> None:
        self.dbmanager = AlphaDBManager()
        self.neutralizations = NEUTRALIZATIONS
        self.datacategories = DATACATEGORIES
        self.delay = DEFAULT_DELAY
        self.run_region = region
        self.COLORS_TO_ASSIGN = COLORS_TO_ASSIGN
        self.selections = {
            "POSITIVE": [
            ],
            "NON_ZERO": [
            ],
            "NON_NAN": [
            ]
        }
        self.combo = [
            '1',
            "combo_a(alpha)",
            'combo_a(alpha,mode=\'algo2\')',
            'combo_a(alpha,mode=\'algo3\')',
            'stats=generate_stats(alpha);1/ts_std_dev(stats.returns,252)',
            'stats=generate_stats(alpha);1/reduce_powersum(self_corr(stats.returns,252),constant=2)',
            'stats=generate_stats(alpha);portfolio_return = ts_sum(stats.returns,252);portfolio_stddev = ts_std_dev(stats.returns,252);portfolio_return/portfolio_stddev',
            'stats=generate_stats(alpha);expected_returns = reduce_avg(self_corr(stats.returns,252), threshold=0);demeaned_returns = stats.returns - expected_returns;covariance_matrix = reduce_sum(self_corr(demeaned_returns* demeaned_returns ,252));portfolio_return = reduce_sum(self_corr(expected_returns,252));portfolio_variance = reduce_sum( (self_corr(covariance_matrix ,252)));portfolio_return/sqrt(portfolio_variance)'
        ]
        self.REGIONS = REGIONS
        self.region_to_process = self.REGIONS[self.run_region]
        self._initialize_selections()

    def _initialize_selections(self) -> None:
        for color in self.COLORS_TO_ASSIGN:
            base_cond = f"own && (color != '{color}')"
            
            conditions = [
                "(prod_correlation <0.6)",
                "(prod_correlation <0.8)",
                "", # just base_cond
                "((long_count > 600 && long_count < 800) || (long_count > 1200 && long_count < 1400))",
                "(turnover > 0.05)",
                "(universe != 'ILLIQUID_MINVOL1M')",
                "(long_count > 500)",
                "((turnover > 0.05 && turnover < 0.08) || (turnover > 0.15 && turnover < 0.18)) && (prod_correlation < 0.80)",
                "((long_count > 600 && long_count < 800) || (long_count > 1200 && long_count < 1400)) && (self_correlation < 0.6)",
                "((operator_count < 5) || (operator_count > 12)) && (prod_correlation < 0.90)",
                "((short_count < 800 && short_count > 600) || (short_count > 1300)) && (prod_correlation < 0.85)",
                "((decay == 1) || (decay == 3) || (decay == 5)) && (self_correlation < 0.65)",
                "(not(in(datacategories, 'fundamental'))) && (turnover < 0.25) && (prod_correlation < 0.80)",
                "(not(in(datacategories, 'pv'))) && (operator_count < 12) && (prod_correlation < 0.85)",
                "(not(in(datacategories, 'model'))) && (long_count > 800) && (prod_correlation < 0.90)",
                "(not(in(datacategories, 'socialmedia'))) && (prod_correlation < 0.95)",
                "(not(in(datacategories, 'news'))) && (self_correlation < 0.7)"
            ]
            
            for cond in conditions:
                if cond:
                    self.selections["POSITIVE"].append(f"{base_cond} && {cond}")
                else:
                    self.selections["POSITIVE"].append(base_cond)

    def creator(self) -> List[Dict[str, Any]]:
        sim_config_list: List[Dict[str, Any]] = []

        base_params = product(
            self.region_to_process,
            self.neutralizations,
            SELECTION_LIMITS,
            self.selections.keys(),
            DECAY_OPTIONS,
        )

        for universe, neutralization, selectionLimit, selectionHandling, decay in base_params:
            current_selections = self.selections[selectionHandling]
            inner_params = product(current_selections, self.combo)
            
            for item_selection_str, item_combo_str in inner_params:
                full_item_data_dict = {
                    "type": "SUPER",
                    "settings": {
                        "nanHandling": "OFF",
                        "instrumentType": "EQUITY",
                        "delay": self.delay,
                        "universe": universe,
                        "truncation": DEFAULT_TRUNCATION,
                        "unitHandling": "VERIFY",
                        "selectionLimit": selectionLimit,
                        "selectionHandling": selectionHandling,
                        "pasteurization": "ON",
                        "region": self.run_region,
                        "language": "FASTEXPR",
                        "decay": decay,
                        "neutralization": neutralization,
                        "visualization": False,
                    },
                    "regular": {
                        "selection": item_selection_str,
                        "combo": item_combo_str
                    }
                }
                sim_config_list.append(full_item_data_dict)
                
        return sim_config_list
