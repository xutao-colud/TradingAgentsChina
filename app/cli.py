from __future__ import annotations

import argparse
import json
import sys

from app.graph.workflow import build_production_workflow, build_sample_workflow
from app.llm.config import DeepSeekConfig
from app.llm.deepseek_client import DeepSeekClient
from app.memory.local_store import LocalMemoryStore
from app.memory.models import FeedbackEvent
from app.market.morning_radar import MorningMoneyRadarClient
from app.market.stock_snapshot import EastmoneyStockSnapshotClient
from app.opportunities.pipeline import OpportunityPipeline
from app.playbooks.catalog import list_playbooks
from app.reporting.render import render_markdown
from app.schemas.report import today_iso


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the A-share research-agent MVP.")
    parser.add_argument("symbol", nargs="?", help="A-share symbol, for example 600519 or 600519.SH")
    parser.add_argument("--date", default=today_iso(), help="Analysis date in YYYY-MM-DD format")
    parser.add_argument("--provider", choices=["production", "sample"], default="production", help="Data provider; production never falls back to sample data")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of Markdown")
    parser.add_argument("--memory-dir", default="data/memory", help="Local memory directory")
    parser.add_argument("--no-save-memory", action="store_true", help="Do not save this analysis to local memory")
    parser.add_argument("--feedback", help="Record feedback instead of running an analysis")
    parser.add_argument(
        "--feedback-type",
        choices=["preference", "outcome", "correction", "rule"],
        default="preference",
        help="Category used with --feedback",
    )
    parser.add_argument("--learned-rule", help="An explicit reusable rule used with --feedback-type rule")
    parser.add_argument("--deepseek-explain", action="store_true", help="Use DeepSeek to explain the deterministic report")
    parser.add_argument("--export-memory", metavar="PATH", help="Export portable personal memory to a JSON file")
    parser.add_argument("--import-memory", metavar="PATH", help="Import and merge a portable personal memory JSON file")
    parser.add_argument("--list-playbooks", action="store_true", help="List public A-share playbook archetypes")
    parser.add_argument("--playbook", metavar="ID", help="Persistently switch the active playbook")
    parser.add_argument("--replay-analysis", metavar="EVENT_ID", help="Replay one saved analysis with later feedback")
    parser.add_argument("--analysis-report-id", help="Saved analysis event ID for outcome feedback")
    parser.add_argument("--outcome-return-pct", type=float, help="Recorded outcome return percentage; requires --feedback-type outcome")
    parser.add_argument("--outcome-days", type=int, help="Outcome holding days; requires --feedback-type outcome")
    parser.add_argument("--opportunity-scan", action="store_true", help="Run the market-first opportunity-pool pipeline")
    parser.add_argument("--opportunity-symbol", action="append", default=[], help="Add an explicit L1 candidate; repeatable")
    parser.add_argument("--opportunity-level", type=int, choices=[1, 2, 3], default=3, help="Maximum opportunity analysis level")
    parser.add_argument("--no-radar", action="store_true", help="Exclude verified intraday radar movers from the opportunity universe")
    parser.add_argument("--list-opportunity-pool", action="store_true", help="Print the latest persisted opportunity pool")
    parser.add_argument("--replay-opportunity", metavar="EVENT_ID", help="Replay one persisted opportunity-pool run")
    return parser


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args()
    store = LocalMemoryStore(args.memory_dir)
    if args.export_memory:
        bundle = store.export_bundle(args.export_memory)
        print(json.dumps({"exported_to": args.export_memory, "event_counts": {key: len(value) for key, value in bundle["events"].items()}}, ensure_ascii=False, indent=2))
        return
    if args.import_memory:
        print(json.dumps({"imported_from": args.import_memory, "added_events": store.import_bundle(args.import_memory)}, ensure_ascii=False, indent=2))
        return
    if args.list_playbooks:
        print(json.dumps({"playbooks": [item.to_dict() for item in list_playbooks()]}, ensure_ascii=False, indent=2))
        return
    if args.playbook:
        profile = store.set_active_playbook(args.playbook)
        if not args.symbol:
            print(json.dumps({"active_playbook": profile.active_playbook, "trading_profile": profile.to_dict()}, ensure_ascii=False, indent=2))
            return
    if args.replay_analysis:
        print(json.dumps(store.replay_analysis(args.replay_analysis), ensure_ascii=False, indent=2))
        return
    if args.replay_opportunity:
        print(json.dumps(store.replay_opportunity_run(args.replay_opportunity), ensure_ascii=False, indent=2))
        return
    if args.list_opportunity_pool:
        print(json.dumps(store.load_opportunity_pool() or {"pipeline_status": "not_run", "candidates": []}, ensure_ascii=False, indent=2))
        return
    if args.opportunity_scan:
        workflow = build_production_workflow() if args.provider == "production" else build_sample_workflow()
        symbols = [*args.opportunity_symbol]
        if args.symbol:
            symbols.insert(0, args.symbol)
        result = OpportunityPipeline(
            workflow,
            store,
            stock_snapshot_client=EastmoneyStockSnapshotClient(),
            morning_radar_client=MorningMoneyRadarClient(),
        ).run(
            analysis_date=args.date,
            explicit_symbols=symbols,
            include_radar=not args.no_radar,
            maximum_level=args.opportunity_level,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if not args.symbol:
        parser.error("symbol is required unless a memory or opportunity-pool command is used")
    if args.feedback:
        feedback = store.record_feedback(
            FeedbackEvent(
                symbol=args.symbol,
                feedback_type=args.feedback_type,
                user_comment=args.feedback,
                learned_rule=args.learned_rule,
                analysis_report_id=args.analysis_report_id,
                outcome_return_pct=args.outcome_return_pct,
                outcome_days=args.outcome_days,
            )
        )
        print(json.dumps({"feedback_event": feedback.to_dict(), "trading_profile": store.load_profile().to_dict()}, ensure_ascii=False, indent=2))
        return
    workflow = build_production_workflow() if args.provider == "production" else build_sample_workflow()
    memory_context = store.build_context(args.symbol)
    default_question = f"分析 {args.symbol}（{args.date}）"
    report = workflow.run(args.symbol, args.date, trading_profile=store.load_profile(), user_question=default_question)
    model_name = "deterministic-mvp"
    if args.deepseek_explain:
        config = DeepSeekConfig.from_env()
        try:
            report = DeepSeekClient(config).explain(report, memory_context)
        except RuntimeError as exc:
            parser.error(str(exc))
        model_name = config.model
    memory_event_id = None
    if not args.no_save_memory:
        event = store.save_analysis(
            report,
            user_query=f"analyze {args.symbol} on {args.date}",
            model_name=model_name,
        )
        memory_event_id = event.id
        store.save_interaction_summary(
            report,
            question=default_question,
            analysis_event_id=event.id,
        )
    if args.json:
        payload = report.to_dict()
        if memory_event_id:
            payload["memory_event_id"] = memory_event_id
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        output = render_markdown(report)
        if memory_event_id:
            output += f"\n\n> 本次分析已保存到本地 Memory：`{memory_event_id}`\n"
        print(output)


if __name__ == "__main__":
    main()
