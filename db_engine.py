import threading
import queue
import time
import logging

# Assuming 'supabase' and 'config' are configured elsewhere
# from supabase_client import supabase 
# import config 

log = logging.getLogger(__name__)

class DBEngine:
    """
    Manages all database read and write operations on a single, dedicated 
    worker thread to prevent main application threads from blocking on I/O.
    """

    def __init__(self):
        # The thread-safe queue where other parts of the app drop DB tasks
        self.db_queue = queue.Queue()
        self.running = True
        
        # Start the single dedicated worker thread
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()
        log.info("ðŸ“± Database Engine: Worker thread started.")

    def _worker_loop(self):
        """
        The main loop for the worker thread. It continuously fetches tasks
        from the queue and executes the corresponding database calls.
        """
        while self.running:
            try:
                # Blocks until a task is available (timeout prevents indefinite block)
                task, args, kwargs = self.db_queue.get(timeout=0.1)
                
                # --- Task Execution Logic ---
                if task == 'update_bankroll':
                    self._update_bankroll_safe(*args, **kwargs)
                elif task == 'log_bet':
                    self._log_bet_safe(*args, **kwargs)
                # Add other tasks here (e.g., 'log_bounty_event', 'update_stats')
                # ----------------------------

                self.db_queue.task_done()
            except queue.Empty:
                # Expected during idle times
                continue
            except Exception as e:
                log.error(f"ðŸ“± Database Error processing task: {e}")
                
        log.info("ðŸ“± Database Engine: Worker thread stopped.")

    # --- Public API (Queue Task Submission) ---

    def update_bankroll(self, user_id, new_bankroll):
        """Adds a bankroll update task to the queue."""
        self.db_queue.put(('update_bankroll', (user_id, new_bankroll), {}))
        
    def log_bet(self, bet_data):
        """Adds a bet logging task to the queue."""
        self.db_queue.put(('log_bet', (bet_data,), {}))

    # Add other public methods here that wrap the queue.put() call
    
    # --- Private Methods (Executed in Worker Thread) ---
    
    def _update_bankroll_safe(self, user_id, new_bankroll):
        """Placeholder for the actual blocking DB call (runs in worker thread)."""
        # Example of a blocking Supabase/SQL operation
        log.debug(f"DB WRITE: Updating bankroll for user {user_id} to {new_bankroll}")
        # supabase.table("users").update({"bankroll": new_bankroll}).eq("id", user_id).execute()
        time.sleep(0.01) # Simulate network latency

    def _log_bet_safe(self, bet_data):
        """Placeholder for the actual blocking DB call (runs in worker thread)."""
        log.debug(f"DB WRITE: Logging bet: {bet_data}")
        # supabase.table("bets").insert(bet_data).execute()
        time.sleep(0.01) # Simulate network latency

    def stop(self):
        """Stops the worker thread cleanly."""
        self.running = False
        self.worker_thread.join()

# Note: The database read functions (e.g., fetching a user's current bankroll) 
# would still be synchronous *reads* but are typically faster than writes. 
# For true high efficiency, even reads might go through a pool or be cached.
