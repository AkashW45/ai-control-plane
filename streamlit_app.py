import streamlit as st
import time
import os
import json
import requests
from dotenv import load_dotenv

from services.jira import get_ticket
from services.jira_context import build_full_ticket_context
from services.jira_search import smart_search, get_project_sprints
from services.llm import analyze_ticket, build_execution_brief, detect_ticket_groups
from services.test_case_generator import generate_test_cases
from services.confluence_search import search_confluence, format_confluence_context


st.set_page_config(layout="wide", page_title="AI Generated Runbook")

st.title("AI Generated Runbook")
st.caption("Jira-Driven DevOps Automation · Powered by Groq")


# ─────────────────────────────────────────────────────────
# Progress bar across top
# ─────────────────────────────────────────────────────────
def render_progress():
    stages = [
        ("1 · Jira",       "ticket"      in st.session_state),
        ("2 · Test Cases", "test_cases"  in st.session_state),
        ("3 · Runbook",    "plan"        in st.session_state),
        ("4 · AI Rec",        "go_no_go"           in st.session_state),
    ]
    cols = st.columns(len(stages))
    for col, (label, done) in zip(cols, stages):
        if done:
            col.success(f"✅ {label}")
        else:
            col.markdown(
                f"<div style='background:#f0f2f6;border-radius:8px;"
                f"padding:8px;text-align:center;color:#888'>{label}</div>",
                unsafe_allow_html=True
            )

render_progress()
st.divider()


# ══════════════════════════════════════════════════════════
# STAGE 1 — JIRA TICKET DISCOVERY
# ══════════════════════════════════════════════════════════
st.markdown("## Stage 1 · Jira Ticket Discovery")
st.caption("Enter a ticket key directly — or search by keyword and sprint to find related tickets")

# ── Mode tabs ─────────────────────────────────────────────
mode = st.radio(
    "How do you want to load a ticket?",
    ["🔑 Direct Ticket Key", "🔎 Keyword / Sprint Search"],
    horizontal=True,
    key="stage1_mode"
)

# ══════════════════════════════════════════════════════════
# MODE A — Direct ticket key entry
# ══════════════════════════════════════════════════════════
if mode == "🔑 Direct Ticket Key":

    col_input, col_btn = st.columns([4, 1])
    with col_input:
        jira_key = st.text_input(
            "Jira Issue Key",
            placeholder="e.g. DEV-1",
            label_visibility="collapsed",
            key="jira_key_input"
        )
    with col_btn:
        fetch_btn = st.button("Fetch", type="primary", use_container_width=True)

    if fetch_btn and jira_key:
        with st.spinner(f"Fetching {jira_key}..."):
            try:
                ticket = get_ticket(jira_key)
                ctx    = build_full_ticket_context(jira_key)
                st.session_state["ticket"]   = ticket
                st.session_state["context"]  = ctx
                st.session_state["jira_key"] = jira_key
                for k in ["test_cases","plan","yaml","job_id","execution",
                          "exec_status","exec_logs","health_checks","verification"]:
                    st.session_state.pop(k, None)
                st.success(f"✅ Loaded {jira_key}")
            except Exception as e:
                st.error(str(e))

# ══════════════════════════════════════════════════════════
# MODE B — Keyword + Sprint search
# ══════════════════════════════════════════════════════════
else:
    s1, s2, s3 = st.columns([2, 2, 1])
    with s1:
        sd_keyword = st.text_input("Keyword", placeholder="e.g. payment gateway, login...", key="sd_keyword")
    with s2:
        sd_sprint  = st.text_input("Sprint Name (optional)", placeholder="e.g. Sprint 1, Release 2.0...", key="sd_sprint")
    with s3:
        sd_project = st.text_input("Project", value="DEV", key="sd_project")

    if st.button("🔍 Search Tickets", type="primary", key="sd_search_btn"):
        if not sd_keyword and not sd_sprint:
            st.warning("Enter at least a keyword or sprint name")
        else:
            with st.spinner("Searching Jira and Confluence..."):
                try:
                    result = smart_search(project=sd_project, keyword=sd_keyword, sprint=sd_sprint)
                    st.session_state["sd_results"] = result
                    st.session_state["sd_selected"] = []
                    kws = [k for k in (sd_keyword or "").split() if len(k) > 2][:5]
                    conf_results = search_confluence(kws, max_results=3)
                    st.session_state["sd_confluence_docs"] = conf_results
                except Exception as e:
                    st.error(str(e))

    if "sd_results" in st.session_state:
        result  = st.session_state["sd_results"]
        tickets = result["tickets"]

        if not tickets:
            st.warning(f"No tickets found. JQL: `{result['jql']}`")
        else:
            direct     = result.get("total_direct", len(tickets))
            discovered = result.get("total_discovered", 0)
            kw_used    = result.get("keywords_used", [])

            if kw_used:
                st.success(
                    f"Keywords matched: {', '.join([f'`{k}`' for k in kw_used])} · "
                    f"**{direct}** direct · **{discovered}** via relationships · "
                    f"**{direct+discovered}** total"
                )
            else:
                st.success(f"Found **{result['total_found']}** tickets")

            with st.expander("JQL Query Used", expanded=False):
                st.code(result["jql"], language="sql")

            conf_docs = st.session_state.get("sd_confluence_docs", [])
            if conf_docs:
                with st.expander(f"📚 {len(conf_docs)} Confluence docs found", expanded=False):
                    for doc in conf_docs:
                        st.markdown(f"**{doc['title']}**")
                        st.caption(doc.get("excerpt","")[:200])
                        st.markdown(f"[Open in Confluence]({doc['url']})")
                        st.divider()

            type_icon = {"Epic":"🟣","Story":"🟢","Bug":"🔴","Task":"🔵","Subtask":"⚪"}.get
            pri_icon  = {"Critical":"🔴","High":"🟠","Medium":"🟡","Low":"🟢"}.get

            sa_col, sn_col, sgen_col, _ = st.columns([1, 1, 2, 3])
            if sa_col.button("Select All", key="sd_all"):
                st.session_state["sd_selected"] = [t["key"] for t in tickets]
                st.rerun()
            if sn_col.button("Clear", key="sd_none"):
                st.session_state["sd_selected"] = []
                st.rerun()
            if sgen_col.button("⚡ Select All & Generate", type="primary", key="sd_all_gen"):
                st.session_state["sd_selected"] = [t["key"] for t in tickets]
                all_keys = [t["key"] for t in tickets]
                st.session_state["sd_sprint_tc"]      = {}
                st.session_state["sd_sprint_tc_keys"] = all_keys
                progress = st.progress(0)
                status   = st.empty()
                for i, key in enumerate(all_keys):
                    status.info(f"Generating test cases for {key} ({i+1}/{len(all_keys)})...")
                    try:
                        ctx    = build_full_ticket_context(key)
                        res    = generate_test_cases(ctx)
                        st.session_state["sd_sprint_tc"][key] = {"context": ctx, "test_cases": res}
                    except Exception as e:
                        st.session_state["sd_sprint_tc"][key] = {"error": str(e)}
                    progress.progress((i + 1) / len(all_keys))
                status.success(f"✅ Done — {len(all_keys)} tickets processed")

                # Auto-load first ticket so Stage 2 unlocks
                first_key = all_keys[0]
                first_data = st.session_state["sd_sprint_tc"].get(first_key, {})
                if "test_cases" in first_data:
                    try:
                        first_ticket = get_ticket(first_key)
                        first_ctx    = build_full_ticket_context(first_key)
                        st.session_state["ticket"]     = first_ticket
                        st.session_state["context"]    = first_ctx
                        st.session_state["jira_key"]   = first_key
                        st.session_state["test_cases"] = first_data["test_cases"]
                        st.session_state["sprint_mode"] = True
                        for k in ["plan","yaml","job_id","execution","exec_status","exec_logs","health_checks"]:
                            st.session_state.pop(k, None)
                    except Exception:
                        pass
                st.rerun()

            def render_ticket_row(ticket, badge=""):
                ti = type_icon(ticket["issue_type"], "🔵")
                pi = pri_icon(ticket["priority"], "🟡")
                is_selected = ticket["key"] in st.session_state.get("sd_selected", [])
                card_cols = st.columns([0.3, 0.7, 4, 1, 1, 1])
                checked = card_cols[0].checkbox("", value=is_selected, key=f"sd_chk_{ticket['key']}", label_visibility="hidden")
                current = st.session_state.get("sd_selected", [])
                if checked and ticket["key"] not in current:
                    current.append(ticket["key"])
                    st.session_state["sd_selected"] = current
                elif not checked and ticket["key"] in current:
                    current.remove(ticket["key"])
                    st.session_state["sd_selected"] = current
                card_cols[1].markdown(f"`{ticket['key']}`")
                card_cols[2].markdown(f"{ti} {ticket['summary'][:70]}")
                card_cols[3].markdown(f"{pi} {ticket['priority']}")
                card_cols[4].markdown(f"_{ticket['issue_type']}_")
                card_cols[5].markdown(f"🔗 {ticket['link_count']}" if ticket['link_count'] > 0 else "")
                if badge or ticket.get("labels"):
                    st.caption(
                        (f"  {badge}" if badge else "") +
                        (f"  · Labels: {' · '.join(ticket['labels'])}" if ticket.get("labels") else "") +
                        (f"  · Sprint: {ticket['sprint']}" if ticket.get("sprint") else "")
                    )

            direct_tickets = result.get("direct_tickets", tickets)
            if direct_tickets:
                st.markdown("**🎯 Direct keyword matches:**")
                for ticket in direct_tickets:
                    render_ticket_row(ticket, "direct match")

            disc_map = result.get("discovered", {})
            if disc_map:
                st.markdown("**🔍 Discovered via relationships:**")
                for key, data in disc_map.items():
                    render_ticket_row(data["ticket"], data["found_via"])

            selected = st.session_state.get("sd_selected", [])
            st.markdown(f"**{len(selected)} tickets selected**")

            btn_col1, btn_col2 = st.columns([2, 2])

            with btn_col1:
                if st.button(
                    f"🧪 Generate Test Cases for {len(selected)} Tickets",
                    type="primary",
                    disabled=len(selected) == 0,
                    key="sd_gen_tc_btn"
                ):
                    st.session_state["sd_sprint_tc"]      = {}
                    st.session_state["sd_sprint_tc_keys"] = selected
                    progress = st.progress(0)
                    status   = st.empty()
                    for i, key in enumerate(selected):
                        status.info(f"Generating test cases for {key}...")
                        try:
                            ctx    = build_full_ticket_context(key)
                            res    = generate_test_cases(ctx)
                            st.session_state["sd_sprint_tc"][key] = {"context": ctx, "test_cases": res}
                        except Exception as e:
                            st.session_state["sd_sprint_tc"][key] = {"error": str(e)}
                        progress.progress((i + 1) / len(selected))
                    status.success(f"✅ Done — {len(selected)} tickets processed")

                    # Auto-load first ticket + set sprint mode so Stage 2 unlocks
                    first_key = selected[0]
                    first_data = st.session_state["sd_sprint_tc"].get(first_key, {})
                    if "test_cases" in first_data:
                        try:
                            first_ticket = get_ticket(first_key)
                            first_ctx    = build_full_ticket_context(first_key)
                            st.session_state["ticket"]    = first_ticket
                            st.session_state["context"]   = first_ctx
                            st.session_state["jira_key"]  = first_key
                            st.session_state["test_cases"] = first_data["test_cases"]
                            st.session_state["sprint_mode"] = True
                            for k in ["plan","yaml","job_id","execution","exec_status","exec_logs","health_checks"]:
                                st.session_state.pop(k, None)
                        except Exception:
                            pass

            with btn_col2:
                if len(selected) == 1:
                    if st.button(f"▶️ Load {selected[0]} into Full Pipeline", key="sd_load_pipeline_btn"):
                        key = selected[0]
                        try:
                            ticket = get_ticket(key)
                            ctx    = build_full_ticket_context(key)
                            st.session_state["ticket"]   = ticket
                            st.session_state["context"]  = ctx
                            st.session_state["jira_key"] = key
                            for k in ["test_cases","plan","yaml","job_id","execution",
                                      "exec_status","exec_logs","health_checks","verification"]:
                                st.session_state.pop(k, None)
                            st.success(f"✅ {key} loaded — scroll down to Stage 2")
                        except Exception as e:
                            st.error(str(e))

_came_from_discovery = (
    "ticket" in st.session_state and
    "sd_sprint_tc" in st.session_state and
    st.session_state.get("jira_key","") in st.session_state.get("sd_sprint_tc", {})
)


st.divider()


# ══════════════════════════════════════════════════════════
# STAGE 2 — GENERATE TEST CASES
# ══════════════════════════════════════════════════════════
st.markdown("## Stage 2 · Generate Test Cases")
st.caption("AI defines what success looks like BEFORE execution — P1/P2 cases feed into Stage 4 AI Recommendation")

if "ticket" not in st.session_state:
    st.warning("⬆️ Complete Stage 1 first")

elif st.session_state.get("sprint_mode") and "test_cases" in st.session_state:
    # ── Sprint mode — show all tickets combined ────────────
    sd_sprint_tc  = st.session_state.get("sd_sprint_tc", {})
    sprint_keys   = st.session_state.get("sd_sprint_tc_keys", st.session_state.get("sprint_keys", []))

    # Build per-ticket summaries
    sprint_summaries = []
    total_all = 0
    total_func = total_neg = total_edge = total_intg = total_regr = total_p1 = 0
    for k in sprint_keys:
        data = sd_sprint_tc.get(k, {})
        ctx  = data.get("context", {})
        tc   = data.get("test_cases", {})
        cov_k = tc.get("coverage_summary", {})
        cases_k = cov_k.get("total_cases", 0)
        total_all  += cases_k
        total_func += cov_k.get("functional", 0)
        total_neg  += cov_k.get("negative", 0)
        total_edge += cov_k.get("edge_cases", 0)
        total_intg += cov_k.get("integration", 0)
        total_regr += cov_k.get("regression", 0)
        total_p1   += sum(1 for t in tc.get("test_suite",[]) if t.get("priority")=="P1")
        sprint_summaries.append({
            "key":        k,
            "summary":    ctx.get("summary", k),
            "issue_type": ctx.get("issue_type", "Task"),
            "risk":       tc.get("risk_level", "Medium"),
            "cases":      cases_k,
        })
    st.session_state["sprint_summaries"] = sprint_summaries

    # Use aggregated coverage
    combined_tc = st.session_state.get("test_cases", {})
    cov = {
        "total_cases": total_all,
        "functional":  total_func,
        "negative":    total_neg,
        "edge_cases":  total_edge,
        "integration": total_intg,
        "regression":  total_regr,
    }

    st.success(f"🚀 Sprint Pipeline — {len(sprint_keys)} tickets · {total_all} total test cases")

    # Sprint tickets overview
    risk_icon = {"Low":"🟢","Medium":"🟡","High":"🟠","Critical":"🔴"}
    type_icon = {"Epic":"🟣","Story":"🟢","Bug":"🔴","Task":"🔵"}
    for s in sprint_summaries:
        ri = risk_icon.get(s["risk"],"🟡")
        ti = type_icon.get(s["issue_type"],"🔵")
        st.write(f"{ti}  · {s['summary'][:60]} · {ri} {s['risk']} · {s['cases']} cases")

    st.divider()
    m1,m2,m3,m4,m5,m6 = st.columns(6)
    m1.metric("Total Cases",  cov.get("total_cases",  0))
    m2.metric("Functional",   cov.get("functional",   0))
    m3.metric("Negative",     cov.get("negative",     0))
    m4.metric("Edge Cases",   cov.get("edge_cases",   0))
    m5.metric("Integration",  cov.get("integration",  0))
    m6.metric("Regression",   cov.get("regression",   0))

    if total_p1:
        st.info(f"🔴 {total_p1} P1 cases across sprint → feed into Stage 4 AI Recommendation")

    if combined_tc.get("qa_notes"):
        st.warning(f"📝 **Sprint QA Notes:** {combined_tc['qa_notes'][:400]}")

    st.caption("Scroll down to Stage 3 to generate the combined sprint runbook.")

elif _came_from_discovery and "test_cases" in st.session_state:
    st.success(f"✅ Test cases already generated from Sprint Discovery — {st.session_state['test_cases']['coverage_summary'].get('total_cases',0)} cases ready")
    st.caption("Scroll down to Stage 3 to build the runbook.")
    if st.button("🔄 Regenerate test cases", key="regen_tc_btn"):
        st.session_state.pop("test_cases", None)
        st.rerun()
else:
    if st.button("🧪 Generate Test Cases", type="primary", key="gen_tc_btn"):
        with st.spinner("Analysing ticket context and generating test cases..."):
            try:
                result = generate_test_cases(st.session_state["context"])
                st.session_state["test_cases"] = result
                for k in ["plan","yaml","job_id","execution",
                          "exec_status","exec_logs","health_checks","verification"]:
                    st.session_state.pop(k, None)
                st.success(f"✅ {result['coverage_summary']['total_cases']} test cases generated")
            except Exception as e:
                st.error(str(e))

# In sprint mode, build combined test suite from all tickets
if st.session_state.get("sprint_mode"):
    sd_sprint_tc = st.session_state.get("sd_sprint_tc", {})
    sprint_keys  = st.session_state.get("sd_sprint_tc_keys", [])
    combined_suite = []
    for k in sprint_keys:
        data = sd_sprint_tc.get(k, {})
        tc_k = data.get("test_cases", {})
        for t in tc_k.get("test_suite", []):
            t_copy = dict(t)
            t_copy["ticket_key"] = k
            combined_suite.append(t_copy)
    if combined_suite:
        st.session_state["test_cases"] = {
            "test_suite": combined_suite,
            "coverage_summary": {"total_cases": len(combined_suite)},
            "risk_level": "High",
            "qa_notes": ""
        }

if "test_cases" in st.session_state:
    tc  = st.session_state["test_cases"]
    cov = tc.get("coverage_summary", {})
    risk = tc.get("risk_level", "Medium")
    risk_icon = {"Low":"🟢","Medium":"🟡","High":"🟠","Critical":"🔴"}.get(risk,"🟡")

    m1,m2,m3,m4,m5,m6,m7 = st.columns(7)
    m1.metric("Risk",        f"{risk_icon} {risk}")
    m2.metric("Total",       cov.get("total_cases", 0))
    m3.metric("Functional",  cov.get("functional",  0))
    m4.metric("Negative",    cov.get("negative",    0))
    m5.metric("Edge Cases",  cov.get("edge_cases",  0))
    m6.metric("Integration", cov.get("integration", 0))
    m7.metric("Regression",  cov.get("regression",  0))

    if tc.get("qa_notes"):
        st.warning(f"📝 **QA Notes:** {tc['qa_notes']}")

    p1_cases = [t for t in tc.get("test_suite",[]) if t.get("priority")=="P1"]
    if p1_cases:
        st.info(f"🔴 **{len(p1_cases)} P1 test cases → feed into Stage 4 AI Recommendation**")

    cat_icon = {
        "Functional":"⚙️","Edge Case":"⚠️","Negative":"❌",
        "Integration":"🔗","Regression":"🔄","Reproduction":"🐛"
    }
    pri_icon = {"P1":"🔴","P2":"🟡","P3":"🟢"}

    f1,f2 = st.columns(2)
    with f1:
        all_cats = sorted(set(t.get("category","") for t in tc.get("test_suite",[])))
        sel_cats = st.multiselect("Filter Category", all_cats, default=all_cats, key="s2_cat")
    with f2:
        all_pris = sorted(set(t.get("priority","") for t in tc.get("test_suite",[])))
        sel_pris = st.multiselect("Filter Priority", all_pris, default=all_pris, key="s2_pri")

    filtered = [
        t for t in tc.get("test_suite",[])
        if t.get("category") in sel_cats and t.get("priority") in sel_pris
    ]

    for test in filtered:
        cat = test.get("category","Functional")
        pri = test.get("priority","P2")
        label = f"{pri_icon.get(pri,'🟡')} {test.get('id','')} · {cat_icon.get(cat,'⚙️')} {cat} · {test.get('title','')}"
        with st.expander(label, expanded=False):
            left, right = st.columns([3,1])
            with left:
                if test.get("preconditions"):
                    st.markdown("**Preconditions**")
                    st.write(test["preconditions"])
                st.markdown("**Steps**")
                for step in test.get("steps",[]):
                    st.write(f"• {step}")
                st.markdown("**Expected Result**")
                st.success(test.get("expected_result",""))
            with right:
                st.write(f"{pri_icon.get(pri,'🟡')} {pri}")
                st.write(f"{cat_icon.get(cat,'⚙️')} {cat}")
                for tag in test.get("tags",[]):
                    st.markdown(f"`{tag}`")

st.divider()


# ══════════════════════════════════════════════════════════
# STAGE 3 — GENERATE AI RUNBOOK
# ══════════════════════════════════════════════════════════
st.markdown("## Stage 3 · Generate AI Runbook")
st.caption("Runbook is informed by test case success criteria — AI plans, Rundeck executes")

if "test_cases" not in st.session_state:
    st.warning("⬆️ Complete Stage 2 first — test cases must define success before runbook is built")
else:
    ticket = st.session_state["ticket"]

    p1_criteria = [
        t["expected_result"]
        for t in st.session_state["test_cases"].get("test_suite",[])
        if t.get("priority") == "P1"
    ]

    if st.session_state.get("sprint_mode"):
        sprint_summaries = st.session_state.get("sprint_summaries", [])
        st.info(f"Sprint Pipeline active: {len(sprint_summaries)} tickets combined")
        with st.expander("Tickets in this sprint deployment", expanded=True):
            for s in sprint_summaries:
                ti = {"Epic":"Epic","Story":"Story","Bug":"Bug","Task":"Task"}.get(s["issue_type"],"")
                st.write(f"-  {s["summary"][:70]} ({ti}) - {s["cases"]} test cases")

    if p1_criteria:
        with st.expander(f"{len(p1_criteria)} P1 success criteria feeding into runbook", expanded=False):
            for c in p1_criteria:
                st.write(f"- {c}")

    if st.session_state.get("sprint_mode"):
        sprint_summaries = st.session_state.get("sprint_summaries", [])
        tickets_text = ", ".join([s["key"] for s in sprint_summaries])
        base_brief = f"Sprint deployment: {tickets_text}"
    else:
        base_brief = build_execution_brief(ticket)


    if p1_criteria: base_brief += chr(10)+chr(10)+(chr(10).join(["Success Criteria:"]+["- "+c for c in p1_criteria]))





    edited_brief = st.text_area(
        "Execution Intent",
        value=base_brief,
        height=150,
        key="brief_input"
    )
    extra_notes = st.text_area(
        "Additional Instructions (optional)",
        placeholder="e.g. include rollback, validate artifact checksum...",
        key="extra_notes"
    )

    final_prompt = edited_brief.strip()
    if extra_notes:
        final_prompt += "\n\nAdditional Notes:\n" + extra_notes.strip()

    if st.button("Generate Runbook", type="primary", key="gen_runbook_btn"):
        with st.spinner("Detecting ticket groups and searching Confluence..."):
            try:
                # Step 1 — detect ticket groups
                ticket_groups = []
                if st.session_state.get("sprint_mode"):
                    sprint_summaries = st.session_state.get("sprint_summaries", [])
                    contexts = [st.session_state.get("sd_sprint_tc",{}).get(s["key"],{}).get("context",{}) for s in sprint_summaries]
                    contexts = [c for c in contexts if c]
                    if len(contexts) >= 2:
                        ticket_groups = detect_ticket_groups(contexts)
                        st.session_state["ticket_groups"] = ticket_groups

                # Step 2 — search Confluence
                keywords = final_prompt.split()[:6]
                conf_docs = search_confluence(keywords, max_results=4)
                conf_context = format_confluence_context(conf_docs)
                st.session_state["confluence_docs"] = conf_docs

                # Step 3 — generate runbook
                plan = analyze_ticket(
                    ticket,
                    final_prompt,
                    confluence_context=conf_context,
                    ticket_groups=ticket_groups if ticket_groups else None
                )
                st.session_state["plan"] = plan
                for k in ["yaml","job_id","execution","exec_status","exec_logs","health_checks","verification"]:
                    st.session_state.pop(k, None)
                st.success(f"Runbook generated" + (f" — {len(ticket_groups)} ticket groups detected" if ticket_groups else "") + (f" — {len(conf_docs)} Confluence docs used" if conf_docs else ""))
            except Exception as e:
                st.error(str(e))

if "plan" in st.session_state:
    plan = st.session_state["plan"]

    # Styled runbook cards matching his UI pattern
    card_css = """
    <style>
    .rb-card{border-radius:16px;padding:1.2rem 1.4rem;background:rgba(255,252,246,0.9);
    border:1px solid rgba(23,33,38,0.1);box-shadow:0 8px 24px rgba(23,33,38,0.08);margin-bottom:1rem;}
    .rb-eyebrow{text-transform:uppercase;letter-spacing:0.12em;font-size:0.72rem;
    color:#52707f;font-weight:700;margin-bottom:0.4rem;}
    .rb-title{font-size:1.15rem;font-weight:700;color:#193646;margin-bottom:0.7rem;}
    .rb-body p{margin:0.3rem 0;line-height:1.6;color:#2d3e46;}
    .rb-list{margin:0.3rem 0 0 1.1rem;padding:0;}
    .rb-list li{margin:0.4rem 0;line-height:1.55;color:#2d3e46;}
    </style>
    """
    st.markdown(card_css, unsafe_allow_html=True)

    def rb_card(title, content, is_list=False):
        if not content:
            return
        import html
        if is_list and isinstance(content, list):
            items = "".join(f"<li>{html.escape(str(c))}</li>" for c in content)
            body = f"<ol class='rb-list'>{items}</ol>"
        else:
            body = f"<p>{html.escape(str(content))}</p>"
        st.markdown(
            f'<div class="rb-card"><div class="rb-eyebrow">Runbook Section</div>'
            f'<div class="rb-title">{html.escape(title)}</div>'
            f'<div class="rb-body">{body}</div></div>',
            unsafe_allow_html=True
        )

    rb_card("Summary",        plan.get("summary", ""))
    rb_card("Probable Cause", plan.get("probable_cause", ""))
    rb_card("Pre-checks",     plan.get("pre_checks", []),  is_list=True)

    # Resolution steps — one code block per step
    if plan.get("steps"):
        import html
        steps_items = ""
        for idx, step in enumerate(plan["steps"], 1):
            cmds = chr(10).join(step.get("commands", []))
            cmds_escaped = html.escape(cmds)
            cmds_escaped = html.escape(cmds)
            steps_items += (
                f'<div style="margin-bottom:1rem">'
                f'<p><strong>{idx}. {html.escape(step.get("description",""))}</strong></p>'
                f'<pre style="background:#1e1e2e;color:#cdd6f4;padding:1rem;border-radius:8px;'
                f'font-size:0.85rem;overflow-x:auto">{cmds_escaped}</pre></div>'
            )
        st.markdown(
            f'<div class="rb-card"><div class="rb-eyebrow">Runbook Section</div>'
            f'<div class="rb-title">Resolution Steps</div>'
            f'<div class="rb-body">{steps_items}</div></div>',
            unsafe_allow_html=True
        )
    # ── Groups integrated into runbook between steps and validation ──
    groups = plan.get("groups", [])
    if groups:
        import html as _html
        type_bg = {"deployment":"D9E1F2","bugfix":"FDECEA","feature":"E8F5E9","migration":"FFF3E0","testing":"EDE7F6"}
        type_hdr = {"deployment":"1F4E78","bugfix":"C0392B","feature":"1A6B3A","migration":"B7860B","testing":"4A235A"}
        for grp in groups:
            gtype    = grp.get("type","deployment")
            gtickets = ", ".join(grp.get("tickets",[]))
            gname    = grp.get("name","")
            bg  = type_bg.get(gtype, "D9E1F2")
            hdr = type_hdr.get(gtype, "1F4E78")
            # Group header card with reason
            greason = grp.get("reason", "")
            st.markdown(
                f'<div style="border-left:4px solid #{hdr};background:#{bg};padding:0.8rem 1rem;'
                f'border-radius:8px;margin:1rem 0 0.5rem 0">'
                f'<span style="font-size:0.72rem;text-transform:uppercase;letter-spacing:0.1em;color:#{hdr};font-weight:700">GROUP · {gtype.upper()}</span>'
                f'<br><strong style="font-size:1.05rem">{_html.escape(gname)}</strong>'
                f'<span style="color:#666;font-size:0.85rem"> — {_html.escape(gtickets)}</span>'
                + (f'<br><span style="font-size:0.8rem;color:#555;font-style:italic">Why grouped: {_html.escape(greason)}</span>' if greason else '')
                + '</div>',
                unsafe_allow_html=True
            )
            col_l, col_r = st.columns(2)
            with col_l:
                if grp.get("pre_checks"):
                    st.markdown("**Pre-checks**")
                    for i,c in enumerate(grp["pre_checks"],1):
                        st.write(f"{i}. {c}")
                if grp.get("validation"):
                    st.markdown("**Validation**")
                    for i,v in enumerate(grp["validation"],1):
                        st.write(f"{i}. {v}")
            with col_r:
                if grp.get("rollback"):
                    st.markdown("**Rollback**")
                    st.error(grp["rollback"])
            if grp.get("steps"):
                st.markdown("**Steps**")
                for idx, step in enumerate(grp["steps"],1):
                    cmds = chr(10).join(step.get("commands",[]))
                    st.markdown(f"*{idx}. {_html.escape(step.get('description',''))}*")
                    st.code(cmds, language="bash")
            st.markdown("---")

    rb_card("Validation", plan.get("validation", []), is_list=True)
    rb_card("Escalation", plan.get("escalation", ""))
    rb_card("Rollback",   plan.get("rollback",   ""))

    # ── Confluence docs used ───────────────────────────────
    conf_docs = st.session_state.get("confluence_docs", [])
    if conf_docs:
        with st.expander(f"📚 {len(conf_docs)} Confluence docs used as context", expanded=False):
            for doc in conf_docs:
                st.markdown(f"**[{doc['title']}]({doc['url']})**")
                st.caption(doc.get("excerpt","")[:200])



st.divider()

# ── Excel Export ──────────────────────────────────────────
if "plan" in st.session_state:
    st.markdown("### 📥 Export Runbook")
    st.caption("Download complete runbook as Excel — Summary, Test Cases, Runbook, AI Recommendations")
    if st.button("Generate Excel Export", type="primary", key="export_xlsx_btn"):
        with st.spinner("Building Excel file..."):
            try:
                from services.runbook_export import export_runbook_excel
                ticket          = st.session_state["ticket"]
                test_cases      = st.session_state.get("test_cases")
                plan            = st.session_state["plan"]
                health_checks   = st.session_state.get("health_checks")
                sprint_summaries= st.session_state.get("sprint_summaries")
                xlsx_bytes = export_runbook_excel(
                    ticket=ticket,
                    test_cases=test_cases,
                    plan=plan,
                    health_checks=health_checks,
                    sprint_summaries=sprint_summaries,
                )
                st.session_state["xlsx_bytes"] = xlsx_bytes
                st.success("Excel file ready")
            except Exception as e:
                st.error(str(e))

    if "xlsx_bytes" in st.session_state:
        jira_key = st.session_state.get("jira_key", "runbook")
        filename = f"runbook_{jira_key}_{__import__("datetime").datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        st.download_button(
            label="Download Excel",
            data=st.session_state["xlsx_bytes"],
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_xlsx_btn"
        )

st.divider()

# ══════════════════════════════════════════════════════════
# STAGE 4 — AI RECOMMENDATION
# ══════════════════════════════════════════════════════════
st.markdown("## Stage 4 · AI Recommendation")
st.caption("AI analyses runtime health metrics and gives a deployment recommendation")

if "test_cases" not in st.session_state:
    st.warning("Complete Stage 2 first")
elif "plan" not in st.session_state:
    st.warning("Complete Stage 3 first")
else:
    # Simulated runtime metrics — fixed values as per demo
    RUNTIME_METRICS = {
        "pods_ready_percent": 100,
        "error_rate_percent": 1.8,
        "latency_p95_ms":     420,
        "decision_required":  True
    }

    if "go_no_go" not in st.session_state:
        # Show the metrics being used
        st.markdown("#### Runtime Health Metrics")
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Pods Ready %",    f"{RUNTIME_METRICS['pods_ready_percent']}%",
                  delta="Healthy", delta_color="normal")
        r2.metric("Error Rate %",    f"{RUNTIME_METRICS['error_rate_percent']}%",
                  delta="Warning", delta_color="inverse")
        r3.metric("Latency P95",     f"{RUNTIME_METRICS['latency_p95_ms']}ms",
                  delta="OK", delta_color="normal")
        r4.metric("Decision Required", "Yes", delta="Review needed", delta_color="inverse")

        if st.button("Get AI Recommendation", type="primary", key="gen_gng_btn"):
            with st.spinner("AI analysing runtime metrics..."):
                try:
                    from services.llm import generate_go_no_go
                    result = generate_go_no_go(
                        plan=st.session_state["plan"],
                        test_cases=st.session_state["test_cases"],
                        sprint_summaries=st.session_state.get("sprint_summaries"),
                        runtime_metrics=RUNTIME_METRICS
                    )
                    st.session_state["go_no_go"] = result
                    st.session_state["runtime_metrics_used"] = RUNTIME_METRICS
                except Exception as e:
                    st.error(str(e))

    if "go_no_go" in st.session_state:
        gng        = st.session_state["go_no_go"]
        verdict    = gng.get("verdict", "PAUSE")
        confidence = float(gng.get("confidence", 0))
        summary    = gng.get("summary", "")
        rm         = st.session_state.get("runtime_metrics_used", RUNTIME_METRICS)

        # ── Runtime metrics display ─────────────────────────
        st.markdown("#### Runtime Health Metrics")
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Pods Ready %",    f"{rm['pods_ready_percent']}%",
                  delta="Healthy", delta_color="normal")
        r2.metric("Error Rate %",    f"{rm['error_rate_percent']}%",
                  delta="Warning",  delta_color="inverse")
        r3.metric("Latency P95",     f"{rm['latency_p95_ms']}ms",
                  delta="OK",       delta_color="normal")
        r4.metric("Decision Required", "Yes", delta="Review needed", delta_color="inverse")

        st.markdown("---")

        # ── Verdict Banner ──────────────────────────────────
        if verdict == "GO":
            st.success(f"## ✅  GO — {summary}")
        elif verdict == "PAUSE":
            st.warning(f"## ⏸️  PAUSE — {summary}")
        else:
            st.error(f"## 🔴  ROLLBACK — {summary}")

        st.caption(f"AI Confidence: {int(confidence * 100)}%")
        st.progress(confidence)

        # ── Recommendation reasons ──────────────────────────
        reasons = gng.get("reasons", [])
        if reasons:
            st.markdown("#### Why this recommendation")
            for r in reasons:
                st.write(f"• {r}")

        # ── Conditions (PAUSE/ROLLBACK only) ───────────────
        conditions = gng.get("conditions", [])
        if conditions and verdict != "GO":
            st.markdown("#### Must resolve before proceeding")
            for c in conditions:
                st.error(f"• {c}")

        st.divider()

        

        # ── Notify Teams ──────────────────────────────────
        st.markdown("### 📣 Notify Team on Microsoft Teams")

        teams_webhook_url = os.getenv("TEAMS_WEBHOOK_URL", "")

        if not teams_webhook_url:
            st.warning("⚠️ TEAMS_WEBHOOK_URL not set in .env")
        else:
            if st.button("📨 Send to Teams", type="primary", key="send_teams_btn"):
                try:
                    import requests as _req
                    from datetime import datetime

                    ticket_s = st.session_state["ticket"]
                    jira_key = st.session_state.get("jira_key", ticket_s.get("key", ""))
                    verdict_emoji = {"GO": "✅", "PAUSE": "⏸️", "ROLLBACK": "🔴"}.get(verdict, "⏸️")

                    pa_payload = {
                        "change_id": jira_key,
                        "project":   ticket_s.get("project", ""),
                        "status":    f"{verdict_emoji} {verdict}",
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    }

                    resp = _req.post(teams_webhook_url, json=pa_payload, timeout=10)
                    if resp.status_code in (200, 202):
                        st.success("✅ Sent to Teams")
                    else:
                        st.error(f"Failed: {resp.status_code}")

                except Exception as e:
                    st.error(str(e))
        render_progress()