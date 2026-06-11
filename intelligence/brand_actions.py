"""Analysis-driven Next-Best-Actions for a brand.

Unlike a templated playbook, every action here is *derived from this brand's
actual computed KPIs* (`framework_kpis.compute_live_values`) and cites the real
numbers behind it — so two brands never get the same generic advice. Each rule
reads a signal (or a combination of signals) and emits a specific, evidence-backed
recommendation with a priority, the channel it runs on, and the team that owns it.
"""
from __future__ import annotations

from typing import Dict, List, Optional


def _num(live: Dict, key: str):
    v = live.get(key)
    return v.get("value") if isinstance(v, dict) else None


def compute_brand_actions(brand, live: Dict[str, dict], is_medicine: bool,
                          role: Optional[str] = None) -> List[dict]:
    """Return prioritised, evidence-cited actions built from the brand's KPIs."""
    A: List[dict] = []

    def add(title, rationale, *, channel, owner, severity, src, priority):
        A.append({
            "title": title, "rationale": rationale,
            "channel": channel, "stakeholder": owner, "severity": severity,
            "priority_score": float(priority), "flywheel_multiplier": 1.0,
            "source_module": src, "evidence": {},
        })

    sov = live.get("mk_share_of_voice") or live.get("bm_voice_share")
    sent = live.get("mk_sentiment_trend") or live.get("ph_patient_sentiment")
    mom = live.get("mk_review_momentum") or live.get("bm_review_momentum")
    complaint = _num(live, "ph_complaint_rate")
    reviews = (live.get("mk_review_trend") or {}).get("count") or (live.get("ph_demand_signal") or {}).get("count")
    evidence = _num(live, "mk_evidence_base") or _num(live, "bm_evidence_base")
    trials = _num(live, "bm_clinical_pipeline")
    news = _num(live, "mk_news_pr")
    fda = _num(live, "ph_safety_signals")
    reimb = _num(live, "bm_reimbursement")
    cat = brand.category or "its category"

    # 1) Demand falling while sentiment holds → availability/distribution, not messaging.
    mom_v = mom.get("value") if mom else None
    sent_v = sent.get("value") if sent else None
    if mom_v is not None and mom_v <= -20 and (sent_v or 0) >= 85:
        add(f"Investigate availability for {brand.name} — demand is cooling, not perception",
            f"Review volume is {mom_v:+d}% vs the prior 90 days while sentiment stays {sent_v}% positive. "
            f"People still like it — so the drop is a distribution / out-of-stock / listing issue, not a messaging one. "
            f"Check pharmacy stock and e-tailer availability before spending on creative.",
            channel="ops", owner="brand", severity="high", src="review_momentum×sentiment", priority=88)
    elif mom_v is not None and mom_v >= 25:
        add(f"Amplify {brand.name} while demand is rising",
            f"Review volume is up {mom_v:+d}% vs the prior 90 days — momentum is on your side. "
            f"Scale spend and secure supply now to ride the curve.",
            channel="paid", owner="marketing", severity="medium", src="review_momentum", priority=70)

    # 2) Share-of-voice gap vs the category leader.
    if sov and sov.get("peers") and (sov.get("rank") or 1) > 1:
        peers = sov["peers"]; leader = peers[0]; share = sov["value"]
        gap = leader["share"] - share
        add(f"Close the voice gap on {leader['name']} in {cat}",
            f"{brand.name} holds {share}% of {cat} review voice — #{sov['rank']} of {sov['peer_count']}, "
            f"{gap} pts behind {leader['name']} ({leader['share']}%). Target share-of-voice campaigns and "
            f"review-generation to close it.",
            channel="organic", owner="marketing", severity="high" if gap >= 10 else "medium",
            src="share_of_voice", priority=72 + min(gap, 20))
    elif sov and (sov.get("rank") == 1):
        add(f"Defend category leadership in {cat}",
            f"{brand.name} leads {cat} voice at {sov['value']}%. Protect the lead — keep review velocity up "
            f"and watch the #2 brand.",
            channel="organic", owner="brand", severity="low", src="share_of_voice", priority=45)

    # 3) Complaint rate elevated.
    if complaint is not None and complaint >= 8:
        add(f"Tackle the complaint drivers behind {brand.name}",
            f"{complaint}% of reviews are negative — above a healthy threshold. Pull the top negative topics and "
            f"address the product/▸counselling issue before scaling spend.",
            channel="comms", owner="brand", severity="high", src="complaint_rate", priority=80)

    # 4) Safety — medicine only.
    if is_medicine and fda and fda > 0:
        rx = live.get("ph_adverse_reactions") or {}
        top = (rx.get("peers") or [{}])[0].get("name")
        add(f"Brief field/medical on {brand.name} safety signals",
            f"{fda} Belgium-occurring adverse-event reports (FAERS)" + (f", led by {top}" if top else "") +
            ". Ensure medical and field teams are briefed and ADR reporting prompts are in materials.",
            channel="hcp", owner="medical", severity="medium", src="safety_signals", priority=66)
    eu = live.get("ph_eu_safety") or {}
    if is_medicine and "▲" in (eu.get("display") or ""):
        add(f"Add ADR-reporting prompts for {brand.name} (▲ additional monitoring)",
            "The active substance is under additional EU safety monitoring (black triangle). Materials and HCP "
            "comms should carry the ▲ and an adverse-reaction reporting prompt.",
            channel="hcp", owner="regulatory", severity="medium", src="black_triangle", priority=60)

    # 5) Evidence / pipeline — medicine.
    if is_medicine and evidence is not None:
        if evidence >= 10:
            add(f"Turn {brand.name}'s evidence base into content",
                f"{evidence} PubMed publications name the substance — strong material for evidence-led claims, "
                f"HCP detailing and thought-leadership.",
                channel="hcp", owner="medical", severity="low", src="evidence_base", priority=48)
        elif evidence == 0:
            add(f"Build the evidence base for {brand.name}",
                "No indexed publications found for the substance — consider real-world-evidence or KOL "
                "publication support to strengthen claims.",
                channel="hcp", owner="medical", severity="low", src="evidence_base", priority=40)
    if is_medicine and trials and trials > 0:
        tp = live.get("bm_trial_phases") or {}
        add(f"Align {brand.name} planning with its clinical pipeline",
            f"{tp.get('detail', str(trials)+' studies')} on ClinicalTrials.gov — factor lifecycle stage and "
            f"competitive threats into launch/defence plans.",
            channel="comms", owner="brand", severity="low", src="clinical_pipeline", priority=42)

    # 6) Reimbursement / pricing — medicine.
    if is_medicine and reimb is not None:
        if reimb == 0:
            add(f"Lead {brand.name} with value/affordability messaging",
                "0% of packs are RIZIV-reimbursed (typical OTC) — patients pay out-of-pocket, so price/value and "
                "pharmacist recommendation are the levers.",
                channel="comms", owner="marketing", severity="low", src="reimbursement", priority=44)
        elif reimb >= 50:
            add(f"Leverage {brand.name}'s reimbursement in HCP messaging",
                f"{reimb}% of packs are RIZIV-reimbursed — a real access advantage to highlight with prescribers.",
                channel="hcp", owner="medical", severity="low", src="reimbursement", priority=43)

    # 7) News spike.
    if news and news >= 25:
        add(f"Monitor the news cycle around {brand.name}",
            f"{news} recent news/press items mention the brand — watch for reputation risk or a moment to amplify.",
            channel="comms", owner="marketing", severity="low", src="news_pr", priority=41)

    # 8) Rx with no consumer-review channel.
    if is_medicine and not reviews:
        add(f"Run {brand.name} through HCP / medical channels, not consumer reviews",
            "This is a prescription product with no consumer-review footprint. Prioritise HCP targeting, medical "
            "education and evidence — the consumer-review KPIs don't apply here.",
            channel="hcp", owner="medical", severity="low", src="channel_fit", priority=38)

    A.sort(key=lambda a: a["priority_score"], reverse=True)
    return A
