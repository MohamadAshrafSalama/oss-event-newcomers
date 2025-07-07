#!/usr/bin/env python3
"""
RQ3 Analysis: Does the project's social-good mission moderate
the relationship between entry mechanism and contributor outcomes?

Stratifies all RQ1/RQ2 analyses by OSS4SG vs non-OSS4SG projects.
"""

import json
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats
import warnings
warnings.filterwarnings("ignore")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(BASE, "08_analysis_results")
OUTPUT = os.path.join(RESULTS, "rq3_oss4sg_results.json")
LATEX_DIR = os.path.join(
    BASE,
    "Event_base_vs_Organic_newcomers_JOURNAL_EXPANDED",
    "tables",
)

def cliffs_delta(x, y):
    nx, ny = len(x), len(y)
    if nx == 0 or ny == 0:
        return 0.0
    more = less = 0
    for xi in x:
        for yj in y:
            if xi > yj:
                more += 1
            elif xi < yj:
                less += 1
    return (more - less) / (nx * ny)

def odds_ratio(a, b, c, d):
    if b == 0 or c == 0:
        return float("inf")
    return (a * d) / (b * c)

def main():
    print("=" * 60)
    print("RQ3: OSS4SG Stratified Analysis")
    print("=" * 60)

    core_df = pd.read_csv(os.path.join(RESULTS, "per_contributor_core_status.csv"))
    ret_df = pd.read_csv(os.path.join(RESULTS, "per_contributor_retention.csv"))

    print(f"\nCore status data: {len(core_df)} contributors")
    print(f"Retention data:   {len(ret_df)} contributors")
    print(f"OSS4SG in core:   {core_df['is_oss4sg'].sum()}")
    print(f"OSS4SG in ret:    {ret_df['is_oss4sg'].sum()}")

    results = {"strata": {}, "interaction_tests": {}}

    for stratum_name, stratum_val in [("OSS4SG", True), ("non-OSS4SG", False)]:
        print(f"\n{'='*50}")
        print(f"  Stratum: {stratum_name}")
        print(f"{'='*50}")

        c = core_df[core_df["is_oss4sg"] == stratum_val].copy()
        r = ret_df[ret_df["is_oss4sg"] == stratum_val].copy()

        event_c = c[c["contributor_type"] == "event"]
        organic_c = c[c["contributor_type"] == "organic"]
        ment_c = c[c["is_mentorship"] == True]
        nonment_c = c[(c["contributor_type"] == "event") & (c["is_mentorship"] == False)]

        stratum_result = {
            "n_projects": int(c["repo"].nunique()),
            "n_event": len(event_c),
            "n_organic": len(organic_c),
            "n_mentorship": len(ment_c),
            "n_nonmentorship": len(nonment_c),
        }

        # --- Core rates ---
        ev_core = event_c["ever_core"].sum()
        ev_total = len(event_c)
        org_core = organic_c["ever_core"].sum()
        org_total = len(organic_c)

        ev_rate = ev_core / ev_total * 100 if ev_total > 0 else 0
        org_rate = org_core / org_total * 100 if org_total > 0 else 0

        table = np.array([[ev_core, ev_total - ev_core],
                          [org_core, org_total - org_core]])
        if table.min() >= 0 and table.sum() > 0:
            chi2, p_chi, _, _ = stats.chi2_contingency(table, correction=False)
            or_val = odds_ratio(ev_core, ev_total - ev_core,
                                org_core, org_total - org_core)
        else:
            chi2, p_chi, or_val = 0, 1.0, 1.0

        print(f"\n  Core Rate (Event vs Organic):")
        print(f"    Event:   {ev_core}/{ev_total} = {ev_rate:.1f}%")
        print(f"    Organic: {org_core}/{org_total} = {org_rate:.1f}%")
        print(f"    chi2={chi2:.2f}, p={p_chi:.4f}, OR={or_val:.2f}")

        stratum_result["core_event_vs_organic"] = {
            "event_core": int(ev_core), "event_total": int(ev_total),
            "event_rate": round(ev_rate, 1),
            "organic_core": int(org_core), "organic_total": int(org_total),
            "organic_rate": round(org_rate, 1),
            "chi2": round(chi2, 2), "p": round(p_chi, 4),
            "odds_ratio": round(or_val, 2),
        }

        # Mentorship vs Non-mentorship core rate
        m_core = ment_c["ever_core"].sum()
        m_total = len(ment_c)
        nm_core = nonment_c["ever_core"].sum()
        nm_total = len(nonment_c)

        m_rate = m_core / m_total * 100 if m_total > 0 else 0
        nm_rate = nm_core / nm_total * 100 if nm_total > 0 else 0

        table2 = np.array([[m_core, m_total - m_core],
                           [nm_core, nm_total - nm_core]])
        if table2.min() >= 0 and table2.sum() > 0 and m_total > 0 and nm_total > 0:
            chi2_m, p_m, _, _ = stats.chi2_contingency(table2, correction=False)
            or_m = odds_ratio(m_core, m_total - m_core,
                              nm_core, nm_total - nm_core)
        else:
            chi2_m, p_m, or_m = 0, 1.0, 1.0

        print(f"\n  Core Rate (Mentorship vs Non-Mentorship):")
        print(f"    Mentorship:     {m_core}/{m_total} = {m_rate:.1f}%")
        print(f"    Non-Mentorship: {nm_core}/{nm_total} = {nm_rate:.1f}%")
        print(f"    chi2={chi2_m:.2f}, p={p_m:.4f}, OR={or_m:.2f}")

        stratum_result["core_ment_vs_nonment"] = {
            "ment_core": int(m_core), "ment_total": int(m_total),
            "ment_rate": round(m_rate, 1),
            "nonment_core": int(nm_core), "nonment_total": int(nm_total),
            "nonment_rate": round(nm_rate, 1),
            "chi2": round(chi2_m, 2), "p": round(p_m, 4),
            "odds_ratio": round(or_m, 2),
        }

        # --- Retention (median survival) ---
        ev_ret = r[r["is_event"] == 1]["survival_months"]
        org_ret = r[r["is_event"] == 0]["survival_months"]

        ev_med = ev_ret.median() if len(ev_ret) > 0 else 0
        org_med = org_ret.median() if len(org_ret) > 0 else 0

        if len(ev_ret) > 0 and len(org_ret) > 0:
            u_stat, p_u = stats.mannwhitneyu(ev_ret, org_ret, alternative="two-sided")
            delta = cliffs_delta(ev_ret.values, org_ret.values)
        else:
            u_stat, p_u, delta = 0, 1.0, 0.0

        print(f"\n  Retention (Event vs Organic):")
        print(f"    Event median:   {ev_med:.1f} months (n={len(ev_ret)})")
        print(f"    Organic median: {org_med:.1f} months (n={len(org_ret)})")
        print(f"    MW p={p_u:.4f}, delta={delta:.2f}")

        stratum_result["retention_event_vs_organic"] = {
            "event_median": round(ev_med, 1), "event_n": int(len(ev_ret)),
            "organic_median": round(org_med, 1), "organic_n": int(len(org_ret)),
            "mw_p": round(p_u, 4), "cliffs_delta": round(delta, 2),
        }

        # --- Pattern distribution by group within stratum ---
        try:
            with open(os.path.join(RESULTS, "first_3months_weekly_results.json")) as f:
                weekly = json.load(f)

            assignments_raw = weekly.get("assignments", [])
            if not assignments_raw:
                with open(os.path.join(RESULTS, "clustering_results.json")) as f:
                    clust = json.load(f)
                assignments_raw = clust.get("assignments", [])

            if assignments_raw and isinstance(assignments_raw[0], dict):
                assign_df = pd.DataFrame(assignments_raw)
                assign_df = assign_df.merge(
                    core_df[["contributor_id", "repo", "is_oss4sg", "is_mentorship", "contributor_type"]].drop_duplicates(),
                    left_on=["repo"],
                    right_on=["repo"],
                    how="left",
                )
        except Exception as e:
            print(f"  Could not load pattern assignments: {e}")

        results["strata"][stratum_name] = stratum_result

    # --- Interaction test: logistic regression ---
    print(f"\n{'='*50}")
    print("  Interaction Test: Entry Mechanism x OSS4SG")
    print(f"{'='*50}")

    core_df["is_event_num"] = (core_df["contributor_type"] == "event").astype(int)
    core_df["is_oss4sg_num"] = core_df["is_oss4sg"].astype(int)
    core_df["interaction"] = core_df["is_event_num"] * core_df["is_oss4sg_num"]
    core_df["ever_core_num"] = core_df["ever_core"].astype(int)

    try:
        from sklearn.linear_model import LogisticRegression

        X = core_df[["is_event_num", "is_oss4sg_num", "interaction"]].values
        y = core_df["ever_core_num"].values

        model = LogisticRegression(max_iter=1000, solver="lbfgs")
        model.fit(X, y)

        coefs = dict(zip(["is_event", "is_oss4sg", "interaction"], model.coef_[0]))
        intercept = model.intercept_[0]

        print(f"  Intercept: {intercept:.4f}")
        for name, coef in coefs.items():
            or_val = np.exp(coef)
            print(f"  {name}: coef={coef:.4f}, OR={or_val:.2f}")

        results["interaction_tests"]["logistic_sklearn"] = {
            "intercept": round(intercept, 4),
            "coefficients": {k: round(v, 4) for k, v in coefs.items()},
            "odds_ratios": {k: round(np.exp(v), 2) for k, v in coefs.items()},
        }
    except ImportError:
        print("  sklearn not available; skipping logistic regression")

    try:
        import statsmodels.api as sm

        X_sm = core_df[["is_event_num", "is_oss4sg_num", "interaction"]].copy()
        X_sm = sm.add_constant(X_sm)
        y_sm = core_df["ever_core_num"]

        logit = sm.Logit(y_sm, X_sm).fit(disp=0)
        print(f"\n  Statsmodels Logistic Regression:")
        print(logit.summary2().tables[1].to_string())

        params = logit.params.to_dict()
        pvalues = logit.pvalues.to_dict()
        conf = logit.conf_int()

        results["interaction_tests"]["logistic_statsmodels"] = {
            "coefficients": {k: round(v, 4) for k, v in params.items()},
            "p_values": {k: round(v, 4) for k, v in pvalues.items()},
            "odds_ratios": {k: round(np.exp(v), 2) for k, v in params.items()},
            "conf_int_95": {k: [round(conf.loc[k, 0], 4), round(conf.loc[k, 1], 4)]
                           for k in params.keys()},
        }

        interaction_p = pvalues.get("interaction", 1.0)
        interaction_or = np.exp(params.get("interaction", 0))
        print(f"\n  Interaction term: OR={interaction_or:.2f}, p={interaction_p:.4f}")
        if interaction_p < 0.05:
            print("  => SIGNIFICANT interaction: OSS4SG moderates the event effect")
        else:
            print("  => Non-significant interaction: OSS4SG does not significantly moderate the event effect")

    except ImportError:
        print("  statsmodels not available; skipping detailed logistic regression")

    # --- Summary comparison ---
    print(f"\n{'='*50}")
    print("  Summary Comparison")
    print(f"{'='*50}")

    for stratum in ["OSS4SG", "non-OSS4SG"]:
        s = results["strata"][stratum]
        print(f"\n  {stratum}:")
        ce = s["core_event_vs_organic"]
        print(f"    Core: Event {ce['event_rate']}% vs Organic {ce['organic_rate']}% (OR={ce['odds_ratio']}, p={ce['p']})")
        re = s["retention_event_vs_organic"]
        print(f"    Retention: Event {re['event_median']} vs Organic {re['organic_median']} months")

    with open(OUTPUT, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {OUTPUT}")

    # --- Generate LaTeX table ---
    generate_latex_table(results)


def generate_latex_table(results):
    os.makedirs(LATEX_DIR, exist_ok=True)
    path = os.path.join(LATEX_DIR, "rq3_oss4sg_results.tex")

    oss4sg = results["strata"]["OSS4SG"]
    non = results["strata"]["non-OSS4SG"]

    oss_ce = oss4sg["core_event_vs_organic"]
    non_ce = non["core_event_vs_organic"]
    oss_re = oss4sg["retention_event_vs_organic"]
    non_re = non["retention_event_vs_organic"]
    oss_cm = oss4sg["core_ment_vs_nonment"]
    non_cm = non["core_ment_vs_nonment"]

    interaction = results.get("interaction_tests", {}).get("logistic_statsmodels", {})
    inter_or = interaction.get("odds_ratios", {}).get("interaction", "---")
    inter_p = interaction.get("p_values", {}).get("interaction", "---")

    def fmt_p(p):
        if isinstance(p, str):
            return p
        if p < 0.001:
            return "$< 0.001$"
        return f"${p:.3f}$"

    lines = [
        r"\begin{table*}[t]",
        r"\centering",
        r"\caption{RQ3: Stratified comparison of contributor outcomes by OSS4SG project status. The interaction test examines whether the event--contributor effect differs across OSS4SG and non-OSS4SG projects.}",
        r"\label{tab:rq3_oss4sg}",
        r"\small",
        r"\begin{tabular}{llcccccc}",
        r"\toprule",
        r"\textbf{Stratum} & \textbf{Comparison} & \textbf{Grp.\ 1} & \textbf{Grp.\ 2} & \textbf{Test} & \textbf{$p$-value} & \textbf{Effect} \\",
        r"\midrule",
        r"\multirow{3}{*}{\textbf{OSS4SG}}",
        f"  & Core: Event vs.\\ Organic & {oss_ce['event_rate']}\\% & {oss_ce['organic_rate']}\\% & $\\chi^2$ & {fmt_p(oss_ce['p'])} & OR $= {oss_ce['odds_ratio']}$ \\\\",
        f"  & Core: Ment.\\ vs.\\ Non-M. & {oss_cm['ment_rate']}\\% & {oss_cm['nonment_rate']}\\% & $\\chi^2$ & {fmt_p(oss_cm['p'])} & OR $= {oss_cm['odds_ratio']}$ \\\\",
        f"  & Retention: Event vs.\\ Organic & {oss_re['event_median']} mo & {oss_re['organic_median']} mo & MW & {fmt_p(oss_re['mw_p'])} & $\\delta = {oss_re['cliffs_delta']}$ \\\\",
        r"\midrule",
        r"\multirow{3}{*}{\textbf{Non-OSS4SG}}",
        f"  & Core: Event vs.\\ Organic & {non_ce['event_rate']}\\% & {non_ce['organic_rate']}\\% & $\\chi^2$ & {fmt_p(non_ce['p'])} & OR $= {non_ce['odds_ratio']}$ \\\\",
        f"  & Core: Ment.\\ vs.\\ Non-M. & {non_cm['ment_rate']}\\% & {non_cm['nonment_rate']}\\% & $\\chi^2$ & {fmt_p(non_cm['p'])} & OR $= {non_cm['odds_ratio']}$ \\\\",
        f"  & Retention: Event vs.\\ Organic & {non_re['event_median']} mo & {non_re['organic_median']} mo & MW & {fmt_p(non_re['mw_p'])} & $\\delta = {non_re['cliffs_delta']}$ \\\\",
        r"\midrule",
        r"\multicolumn{2}{l}{\textbf{Interaction (Entry $\times$ OSS4SG)}}",
        f"  & \\multicolumn{{5}}{{l}}{{Logistic regression: OR $= {inter_or}$, $p = {fmt_p(inter_p)}$}} \\\\",
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table*}",
    ]

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"LaTeX table saved to {path}")


if __name__ == "__main__":
    main()
