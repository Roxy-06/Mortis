import os
import time
import argparse
import logging
import threading
from dotenv import load_dotenv

load_dotenv()

from agents.ta_agent import TAAgent
from engine.paper_trader import PaperTrader
from tools.market_data import fetch_current_price

def run_single_cycle():
    """Run one 15-minute strategy evaluation cycle"""
    print(f"\n[Mortis Cycle] Starting analysis at {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}...")
    agent = TAAgent()
    result = agent.analyze_and_trade()
    
    rec = result["decision_record"]
    plan = result["trade_plan"]
    
    print(f"-> Symbol Price: ${result['snapshot']['price']:,.2f}")
    print(f"-> Agent Proposal: Direction={result['agent_decision'].get('direction')} | Conf={plan['raw_confidence']:.2f}")
    print(f"-> Rationale: {result['agent_decision'].get('rationale')}")
    print(f"-> Final Action: {plan['action'].upper()}")
    
    if plan['action'] != "no_trade":
        print(f"  |-- Entry: ${plan['entry']} | SL: ${plan['stop_loss']} | TP: ${plan['take_profit']} | Size: {plan['size_btc']} BTC")
    else:
        print(f"  |-- Reason: {plan.get('reason_if_no_trade')}")
        
    print(f"[PROOF] SHA-256 Decision Hash: {rec['decision_hash']}")
    return result

def run_loop(
    interval_sec: int = 900,
    poll_sec: int = 5,
    stop_event: threading.Event | None = None,
):
    """Run AI analysis every 15 minutes and settle against live prices every few seconds."""
    print("=========================================")
    print(" MORTIS AUTONOMOUS ENGINE RUNNING ")
    print("=========================================")
    trader = PaperTrader()
    stop_event = stop_event or threading.Event()

    while not stop_event.is_set():
        try:
            run_single_cycle()
            start_time = time.time()
            while time.time() - start_time < interval_sec and not stop_event.is_set():
                if stop_event.wait(poll_sec):
                    break
                price = fetch_current_price("BTCUSDT")
                trader.settle_open_position(price)
                
        except KeyboardInterrupt:
            print("\n[Mortis Engine] Shutdown requested.")
            break
        except Exception as e:
            logging.exception("[Mortis Engine] Autonomous cycle failed")
            if stop_event.wait(10):
                break

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mortis Trading Engine")
    parser.add_argument("--once", action="store_true", help="Run a single cycle and exit")
    args = parser.parse_args()
    
    if args.once:
        run_single_cycle()
    else:
        run_loop()
