PV_GROUPS = {
    "USA": [
        "sta2_top3000_fact3_c50",
        "sta2_top3000_fact4_c20",
        "sta2_top3000_fact4_c10",
        "sta2_top3000_fact3_c20",
        "sta2_top3000_fact1_c10",
        "sta2_top3000_fact2_c50",
        "sta2_top3000_fact1_c50",
        "sta2_top3000_fact4_c5",
        "sta2_top3000_fact4_c50",
        "sta2_top3000_fact2_c2"
    ],
    "GLB": [
        "pv13_6l_scibr",
        "pv13_52_minvol_1m_sector",
        "pv13_52_minvol_1m_all_delay_1_sector",
        "pv13_1l_scibr",
        "pv13_5l_scibr",
        "pv13_2l_scibr",
        "pv13_20_minvol_1m_sector",
        "pv13_2_sector",
        "pv13_10_minvol_1m_sector",
        "pv13_2_minvol_1m_sector"
    ],
    "EUR": [
        "sta1_allc10",
        "sta3_pvgroup4_sector",
        "sta1_allc20",
        "sta1_allc2",
        "sta2_top1200_fact4_c50",
        "sta2_top1200_fact1_c50",
        "sta2_top1200_fact3_c50",
        "sta3_pvgroup5_sector",
        "sta1_top1200c2",
        "sta2_top1200_fact3_c20"
    ],
    "ASI": [
        "pv13_2_f4_g3_minvol_1m_sector",
        "pv13_10_f3_g2_minvol_1m_sector",
        "pv13_5_minvol_1m_sector",
        "pv13_5_f3_g2_minvol_1m_sector",
        "pv13_4l_scibr",
        "pv13_3l_scibr",
        "sta2_top700_jpn_513_top700_fact3_c10",
        "sta2_top2000_jpn_513_top2000_fact3_c50",
        "sta2_all_jpn_513_all_fact1_c10",
        "sta2_all_jpn_513_all_fact4_c10"
    ],
    "CHN": [
        "sta1_top2000c30",
        "sta1_top2000c20",
        "sta1_top2000c10",
        "sta1_top3000c20",
        "sta1_top3000c30",
        "sta1_top3000c5",
        "sta1_top3000c10",
        "sta1_top2000c2",
        "sta1_top3000c2",
        "sta1_top2000c5"
    ],
    "HKG": [
        "sta2_top2000_xjp_513_top2000_fact3_c20",
        "sta2_all_xjp_513_all_fact3_c50",
        "sta2_all_xjp_513_all_fact4_c10",
        "sta2_all_xjp_513_all_fact3_c20",
        "sta2_top2000_xjp_513_top2000_fact1_c20",
        "sta2_all_xjp_513_all_fact4_c50",
        "sta2_all_xjp_513_all_fact3_c10",
        "sta2_all_xjp_513_all_fact1_c50",
        "sta2_top2000_xjp_513_top2000_fact3_c10",
        "sta2_all_xjp_513_all_fact4_c20"
    ],
    "IND": [
        "sta1_allxjp_513_c20",
        "sta1_allxjp_513_c50",
        "sta1_top2000xjp_513_c50",
        "sta1_allxjp_513_c10",
        "sta1_top2000xjp_513_c20",
        "sta1_top2000xjp_513_c10",
        "sta1_allxjp_513_c2",
        "sta2_allfactor_xjp_513_3",
        "sta1_allxjp_513_c5",
        "sta1_top2000xjp_513_c2"
    ],
    "KOR": [
        "sta2_all_xjp_513_all_fact4_c5",
        "sta2_all_xjp_513_all_fact3_c5",
        "sta2_all_xjp_513_all_fact2_c5",
        "sta2_all_xjp_513_all_fact4_c2",
        "sta2_top2000_xjp_513_top2000_fact1_c50",
        "sta2_all_xjp_513_all_fact1_c20",
        "sta2_all_xjp_513_all_fact2_c2",
        "sta2_top2000_xjp_513_top2000_fact2_c10",
        "sta2_all_xjp_513_all_fact1_c2",
        "sta2_all_xjp_513_all_fact2_c10"
    ],
    "COMMON": [
        "bucket(rank(cap), range='0.1, 1, 0.1')",
        "bucket(group_rank(cap, sector),range='0.1, 1, 0.1')",
        "bucket(rank(ts_std_dev(returns,20)),range = '0.1, 1, 0.1')",
        "bucket(rank(close*volume),range = '0.1, 1, 0.1')",
    ],
}

ATOM_GROUPS = [
    "market",
    "sector",
    "industry",
    "subindustry",
    "exchange",
    "country",
    "currency",
]

FUNDAMENTAL_GROUPS = {
    "ASI": [
        "bucket(rank(total_assets_annual_atot),range='0.1, 1, 0.1')",
        "bucket(group_rank(total_assets_annual_atot, sector),range='0.1, 1, 0.1')",
        "bucket(rank(fnd94_q_q_qta),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd94_q_q_qta, sector),range='0.1, 1, 0.1')"
    ],
    "CHN": [
        "bucket(rank(fnd5_06_af_sb),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd5_06_af_sb, sector),range='0.1, 1, 0.1')",
        "bucket(rank(fnd5_14_af_sb),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd5_14_af_sb, sector),range='0.1, 1, 0.1')",
        "bucket(rank(fnd27_04000_tot_assets_value),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd27_04000_tot_assets_value, sector),range='0.1, 1, 0.1')",
        "bucket(rank(fnd27_01000_tot_assets_value),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd27_01000_tot_assets_value, sector),range='0.1, 1, 0.1')",
        "bucket(rank(fnd27_09000_tot_assets_value),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd27_09000_tot_assets_value, sector),range='0.1, 1, 0.1')"
    ],
    "EUR": [
        "bucket(rank(fnd28_anlev_value_08236a),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd28_anlev_value_08236a, sector),range='0.1, 1, 0.1')",
        "bucket(rank(fnd28_keyfinancials_value_07230a),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd28_keyfinancials_value_07230a, sector),range='0.1, 1, 0.1')",
        "bucket(rank(fnd28_anlev_value_08241a),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd28_anlev_value_08241a, sector),range='0.1, 1, 0.1')",
        "bucket(rank(fnd23_intfvmfm2_tota),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd23_intfvmfm2_tota, sector),range='0.1, 1, 0.1')",
        "bucket(rank(fnd23_annfv1a_tota),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd23_annfv1a_tota, sector),range='0.1, 1, 0.1')"
    ],
    "GLB": [
        "bucket(rank(fnd23_tot_assets),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd23_tot_assets, sector),range='0.1, 1, 0.1')",
        "bucket(rank(fnd28_astut_value_08416a),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd28_astut_value_08416a, sector),range='0.1, 1, 0.1')",
        "bucket(rank(fnd28_levliqa_value_08236a),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd28_levliqa_value_08236a, sector),range='0.1, 1, 0.1')",
        "bucket(rank(fnd23_annfvmfm2_tota),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd23_annfvmfm2_tota, sector),range='0.1, 1, 0.1')",
        "bucket(rank(fnd28_value_15121),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd28_value_15121, sector),range='0.1, 1, 0.1')"
    ],
    "HKG": [
        "bucket(rank(fnd4_06_af_sb),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd4_06_af_sb, sector),range='0.1, 1, 0.1')",
        "bucket(rank(fnd4_54_lpt_sb),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd4_54_lpt_sb, sector),range='0.1, 1, 0.1')",
        "bucket(rank(fnd4_14_af_sb),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd4_14_af_sb, sector),range='0.1, 1, 0.1')",
        "bucket(rank(fnd17_atotd2ast),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd17_atotd2ast, sector),range='0.1, 1, 0.1')",
        "bucket(rank(fnd17_qtotd2ast),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd17_qtotd2ast, sector),range='0.1, 1, 0.1')"
    ],
    "IND": [
        "bucket(rank(total_assets_annual_atot),range='0.1, 1, 0.1')",
        "bucket(group_rank(total_assets_annual_atot, sector),range='0.1, 1, 0.1')",
        "bucket(rank(fnd94_q_q_qta),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd94_q_q_qta, sector),range='0.1, 1, 0.1')",
        "bucket(rank(fnd17_atotd2ast),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd17_atotd2ast, sector),range='0.1, 1, 0.1')"
    ],
    "KOR": [
        "bucket(rank(fnd28_value_08241q),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd28_value_08241q, sector),range='0.1, 1, 0.1')",
        "bucket(rank(fnd28_value_08236q),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd28_value_08236q, sector),range='0.1, 1, 0.1')",
        "bucket(rank(fnd17_qtotd2ast),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd17_qtotd2ast, sector),range='0.1, 1, 0.1')",
        "bucket(rank(fnd28_fsq1_value_02999q),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd28_fsq1_value_02999q, sector),range='0.1, 1, 0.1')",
        "bucket(rank(fnd28_nddq1_value_02999q),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd28_nddq1_value_02999q, sector),range='0.1, 1, 0.1')"
    ],
    "USA": [
        "bucket(rank(fnd13_rkdbalancesheetq_atot),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd13_rkdbalancesheetq_atot, sector),range='0.1, 1, 0.1')",
        "bucket(rank(fnd28_anlev_value_08287a),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd28_anlev_value_08287a, sector),range='0.1, 1, 0.1')",
        "bucket(rank(fnd28_newa3_value_15121a),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd28_newa3_value_15121a, sector),range='0.1, 1, 0.1')",
        "bucket(rank(fnd23_tot_assets),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd23_tot_assets, sector),range='0.1, 1, 0.1')",
        "bucket(rank(fnd28_anaut_value_08416a),range='0.1, 1, 0.1')",
        "bucket(group_rank(fnd28_anaut_value_08416a, sector),range='0.1, 1, 0.1')"
    ],
    "COMMON": [
        "bucket(rank(assets),range='0.1, 1, 0.1')",
        "bucket(group_rank(assets, sector),range='0.1, 1, 0.1')"
    ]
}
