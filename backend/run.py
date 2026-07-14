import os

from app import attach_obstacle_service, create_app
from app.obstacle import ObstacleService

DEBUG = True
USE_RELOADER = True

app = create_app()

# Start the obstacle subsystem exactly once. Under Flask's debug reloader the
# module is imported in both the parent (supervisor) and the child; only the
# child sets WERKZEUG_RUN_MAIN=true. Guard on it so the background threads start
# once. Without the reloader, start unconditionally.
_run_workers = (not USE_RELOADER) or os.environ.get("WERKZEUG_RUN_MAIN") == "true"

if _run_workers:
    _service = ObstacleService()
    _service.start()
    attach_obstacle_service(app, _service)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=DEBUG, threaded=True, use_reloader=USE_RELOADER)
