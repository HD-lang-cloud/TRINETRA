import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = Path(__file__).resolve().parent
for p in [str(ROOT_DIR), str(BACKEND_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from flask import Flask, jsonify, request
from flask_cors import CORS

from config import get_config
from utils.logger import setup_logger
from utils.errors import AppException, format_response
from routes.system import system_bp
from routes.products import products_bp
from routes.inventory import inventory_bp
from routes.suppliers import suppliers_bp
from routes.intelligence import intelligence_bp
from routes.forecasts import forecasts_bp
from routes.replenishment import replenishment_bp
from routes.simulation import simulation_bp
from routes.decisions import decisions_bp
from routes.network import network_bp
from routes.capital import capital_bp


def create_app(config_name: str = None) -> Flask:
    """
    Application Factory for TRINETRA.
    Initializes configuration, static frontend serving, logging, CORS, error handlers, and route blueprints.
    """
    frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
    app = Flask(__name__, static_folder=frontend_dir, static_url_path="")
    config_class = get_config(config_name)
    app.config.from_object(config_class)

    # Initialize structured logger
    logger = setup_logger("trinetra", level=app.config.get("LOG_LEVEL", "INFO"))
    app.logger = logger

    # Enable Cross-Origin Resource Sharing
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Register Blueprints
    app.register_blueprint(system_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(suppliers_bp)
    app.register_blueprint(intelligence_bp)
    app.register_blueprint(forecasts_bp)
    app.register_blueprint(replenishment_bp)
    app.register_blueprint(simulation_bp)
    app.register_blueprint(decisions_bp)
    app.register_blueprint(network_bp)
    app.register_blueprint(capital_bp)

    # Workstation Web App Landing
    @app.route("/", methods=["GET"])
    def index():
        index_file = os.path.join(frontend_dir, "index.html")
        if os.path.exists(index_file):
            return app.send_static_file("index.html")
        return jsonify({
            "platform": "TRINETRA",
            "descriptor": "AI-Native Inventory Resilience & Decision Intelligence Platform",
            "tagline": "SEE. FORESEE. PREPARE.",
            "status": "operational",
            "docs": "/api/system/health"
        }), 200

    # Custom Application Exception Handler
    @app.errorhandler(AppException)
    def handle_app_exception(err: AppException):
        return format_response(
            message=err.message,
            error={
                "code": err.error_code,
                "message": err.message,
                "details": err.details
            },
            status_code=err.status_code
        )

    # 404 Not Found Handler
    @app.errorhandler(404)
    def handle_404(err):
        return format_response(
            message=f"Endpoint '{request.path}' not found.",
            error={"code": "NOT_FOUND", "message": str(err)},
            status_code=404
        )

    # 405 Method Not Allowed Handler
    @app.errorhandler(405)
    def handle_405(err):
        return format_response(
            message=f"HTTP method '{request.method}' not allowed on '{request.path}'.",
            error={"code": "METHOD_NOT_ALLOWED", "message": str(err)},
            status_code=405
        )

    # 500 Internal Server Error Handler
    @app.errorhandler(500)
    def handle_500(err):
        app.logger.error(f"Internal server error: {err}")
        return format_response(
            message="An unexpected internal error occurred.",
            error={"code": "INTERNAL_SERVER_ERROR", "message": str(err)},
            status_code=500
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=app.config.get("DEBUG", True))