OPEN_EVENTS = [
    "ts_arg_max(volume, 5) == 0",
    "ts_corr(close, volume, 20) < 0",
    "ts_corr(close, volume, 5) < 0",
    "ts_mean(volume,10)>ts_mean(volume,60)",
    "group_rank(ts_std_dev(returns,60), sector) > 0.7",
    "ts_zscore(returns,60) > 2",
    "ts_arg_min(volume, 5) > 3",
    "ts_std_dev(returns, 5) > ts_std_dev(returns, 20)",
    "ts_arg_max(close, 5) == 0",
    "ts_arg_max(close, 20) == 0",
    "ts_corr(close, volume, 5) > 0",
    "ts_corr(close, volume, 5) > 0.3",
    "ts_corr(close, volume, 5) > 0.5",
    "ts_corr(close, volume, 20) > 0",
    "ts_corr(close, volume, 20) > 0.3",
    "ts_corr(close, volume, 20) > 0.5",
    "ts_regression(returns, %s, 5, lag = 0, rettype = 2) > 0",
    "ts_regression(returns, %s, 20, lag = 0, rettype = 2) > 0",
    "ts_regression(returns, ts_step(20), 20, lag = 0, rettype = 2) > 0",
    "ts_regression(returns, ts_step(5), 5, lag = 0, rettype = 2) > 0",
]

EXIT_EVENTS = ["abs(returns) > 0.1", "-1"]

USA_EVENTS = [
    "rank(rp_css_business) > 0.8",
    "ts_rank(rp_css_business, 22) > 0.8",
    "rank(vec_avg(mws82_sentiment)) > 0.8",
    "ts_rank(vec_avg(mws82_sentiment),22) > 0.8",
    "rank(vec_avg(nws48_ssc)) > 0.8",
    "ts_rank(vec_avg(nws48_ssc),22) > 0.8",
    "rank(vec_avg(mws50_ssc)) > 0.8",
    "ts_rank(vec_avg(mws50_ssc),22) > 0.8",
    "ts_rank(vec_sum(scl12_alltype_buzzvec),22) > 0.9",
    "pcr_oi_270 < 1",
    "pcr_oi_270 > 1",
]

ASI_EVENTS = ["rank(vec_avg(mws38_score)) > 0.8", "ts_rank(vec_avg(mws38_score),22) > 0.8"]

EUR_EVENTS = [
    "rank(rp_css_business) > 0.8",
    "ts_rank(rp_css_business, 22) > 0.8",
    "rank(vec_avg(oth429_research_reports_fundamental_keywords_4_method_2_pos)) > 0.8",
    "ts_rank(vec_avg(oth429_research_reports_fundamental_keywords_4_method_2_pos),22) > 0.8",
    "rank(vec_avg(mws84_sentiment)) > 0.8",
    "ts_rank(vec_avg(mws84_sentiment),22) > 0.8",
    "rank(vec_avg(mws85_sentiment)) > 0.8",
    "ts_rank(vec_avg(mws85_sentiment),22) > 0.8",
    "rank(mdl110_analyst_sentiment) > 0.8",
    "ts_rank(mdl110_analyst_sentiment, 22) > 0.8",
    "rank(vec_avg(nws3_scores_posnormscr)) > 0.8",
    "ts_rank(vec_avg(nws3_scores_posnormscr),22) > 0.8",
    "rank(vec_avg(mws36_sentiment_words_positive)) > 0.8",
    "ts_rank(vec_avg(mws36_sentiment_words_positive),22) > 0.8",
]

GLB_EVENTS = [
    "rank(vec_avg(mdl109_news_sent_1m)) > 0.8",
    "ts_rank(vec_avg(mdl109_news_sent_1m),22) > 0.8",
    "rank(vec_avg(nws20_ssc)) > 0.8",
    "ts_rank(vec_avg(nws20_ssc),22) > 0.8",
    "vec_avg(nws20_ssc) > 0",
    "rank(vec_avg(nws20_bee)) > 0.8",
    "ts_rank(vec_avg(nws20_bee),22) > 0.8",
    "rank(vec_avg(nws20_qmb)) > 0.8",
    "ts_rank(vec_avg(nws20_qmb),22) > 0.8",
]

CHN_EVENTS = [
    "rank(vec_avg(oth111_xueqiunaturaldaybasicdivisionstat_senti_conform)) > 0.8",
    "ts_rank(vec_avg(oth111_xueqiunaturaldaybasicdivisionstat_senti_conform),22) > 0.8",
    "rank(vec_avg(oth111_gubanaturaldaydevicedivisionstat_senti_conform)) > 0.8",
    "ts_rank(vec_avg(oth111_gubanaturaldaydevicedivisionstat_senti_conform),22) > 0.8",
    "rank(vec_avg(oth111_baragedivisionstat_regi_senti_conform)) > 0.8",
    "ts_rank(vec_avg(oth111_baragedivisionstat_regi_senti_conform),22) > 0.8",
]

KOR_EVENTS = [
    "rank(vec_avg(mdl110_analyst_sentiment)) > 0.8",
    "ts_rank(vec_avg(mdl110_analyst_sentiment),22) > 0.8",
    "rank(vec_avg(mws38_score)) > 0.8",
    "ts_rank(vec_avg(mws38_score),22) > 0.8",
]

TWN_EVENTS = [
    "rank(vec_avg(mdl109_news_sent_1m)) > 0.8",
    "ts_rank(vec_avg(mdl109_news_sent_1m),22) > 0.8",
    "rank(rp_ess_business) > 0.8",
    "ts_rank(rp_ess_business,22) > 0.8",
]
