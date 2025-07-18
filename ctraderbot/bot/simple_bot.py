# simple_bot.py
from ctrader_open_api import Client
from .trading import request_unrealized_pnl
from .event_handlers import register_callbacks
from twisted.internet import reactor
import datetime
from .trading import _get_or_create_segment_and_trade, _open_positions_for_trade
from twisted.internet.threads import deferToThread


class SimpleBot:
    def __init__(self, client: Client, access_token: str, account_pk: int, account_id: int, symbol_id: int):
        self.client = client
        self.access_token = access_token
        self.account_pk = account_pk 
        self.account_id = account_id
        self.symbol_id = symbol_id
        self.is_shutting_down = False
        self.positions: dict[int, dict] = {}
        self.trade_couple: dict[int, dict] = {}
        self.pnl_timer = None
        self.is_refreshing_token = False # Add this line

        self.current_balance = None # Used to initalize price from boot

        register_callbacks(self)

    def start(self):
        self.client.startService()
        reactor.run()
    
    def start_schedules(self):
        """Starts all recurring tasks for the bot."""
        # Start your other tasks
        self.schedule_pnl_updates()

        # Start the new specific task for 19:00
        self.schedule_periodic_task()
        # self.schedule_daily_task_at_19()
    
    def schedule_pnl_updates(self):
        """Schedules the bot to request PnL updates every 1 seconds."""
        request_unrealized_pnl(self)
        reactor.callLater(1, self.schedule_pnl_updates)
    
    def schedule_daily_task_at_19(self):
        """Calculates the delay to the next 19:00 and schedules the task."""
        now = datetime.datetime.now()
        
        # Set the target time to today at 19:00
        target_time = now.replace(hour=19, minute=0, second=0, microsecond=0)
        
        # If it's already past 19:00 today, schedule it for tomorrow
        if now > target_time:
            print("[SCHEDULER] It's past 19:00 today. Scheduling for tomorrow.")
            target_time += datetime.timedelta(days=1)
            
        # Calculate the delay in seconds
        delay_seconds = (target_time - now).total_seconds()
        
        print(f"[SCHEDULER] Specific 19:00 task will run at {target_time} (in {delay_seconds:.0f} seconds).")
        reactor.callLater(delay_seconds, self.run_daily_task_at_19)

    def run_daily_task_at_19(self):
        """
        This is the actual task that will run at 19:00.
        It reschedules itself to run again the next day.
        """
        print(f"🎉 [SCHEDULER] Running specific task at {datetime.datetime.now()}! 🎉")
        
        # --- PLACE YOUR 19:00-SPECIFIC LOGIC HERE ---
        _get_or_create_segment_and_trade(self)
        
        # Reschedule this task to run again tomorrow (24 hours * 3600 seconds)
        # This creates a recurring daily task.
        reactor.callLater(24 * 3600, self.run_daily_task_at_19)
    
    def emergency_stop_all_trades(self):
        """
        Iterates through all known running positions and sends a close command for each.
        """
        print("[!!!] EMERGENCY STOP INITIATED! Attempting to close all active positions.")
        
        # Make a copy of the items to avoid issues with modifying the dict while iterating
        positions_to_close = list(self.positions.items())
        
        if not positions_to_close:
            print("[INFO] No active positions found in memory to close.")
            return

        closed_count = 0
        for position_id, pos_data in positions_to_close:
            if pos_data.get("status") == "OPEN":
                from .trading import close_position
                volume_to_close = pos_data.get("volume", 0)
                if volume_to_close > 0:
                    print(f"--> Sending EMERGENCY CLOSE for position {position_id}")
                    close_position(self, position_id, volume_to_close)
                    closed_count += 1
        
        print(f"[INFO] Emergency close commands sent for {closed_count} positions.")

    ##### DEVELOPMENT METHODS ONLY #####

    def schedule_periodic_task(self):
        """Schedules a task to run for the first time after 2 minutes."""
        from twisted.internet import reactor
        print("[SCHEDULER] Starting periodic task. First run in 2 minutes.")
        # Schedule the first execution after 120 seconds.
        reactor.callLater(120, self.run_periodic_task)

    def run_periodic_task(self):
        """
        This is the actual task that will run every 2 minutes.
        It reschedules itself to run again.
        """
        from twisted.internet import reactor
        print(f"🎉 [SCHEDULER] Running periodic task at {datetime.datetime.now()}! 🎉")
        
        # 1. Ask the function to do one specific thing: check and maybe create a trade.
        new_trade = _get_or_create_segment_and_trade(self)

        # 2. Only act if something new was actually created.
        if new_trade:
            # 3. Perform the specific action needed: open positions for this new trade.
            deferToThread(_open_positions_for_trade, new_trade, self)
        
        # --- Reschedule this same task to run again in 2 minutes (120 seconds) ---
        print("[SCHEDULER] Rescheduling task for 2 minutes from now.")
        reactor.callLater(120, self.run_periodic_task)
