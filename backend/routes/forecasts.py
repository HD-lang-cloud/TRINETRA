from flask import Blueprint, request
from ml.service import ForecastingService
from utils.errors import format_response

forecasts_bp = Blueprint("forecasts", __name__)
forecast_service = ForecastingService()


@forecasts_bp.route("/api/forecasts/<int:product_id>", methods=["GET"])
def get_product_forecast(product_id: int):
    """
    Retrieves or generates 14-day multi-model benchmark demand forecast,
    confidence intervals (80% and 95%), and accuracy metrics (MAE, RMSE, sMAPE).
    """
    horizon = request.args.get("horizon", default=14, type=int)
    force_refresh = request.args.get("refresh", "").lower() in ("true", "1")

    if force_refresh:
        data = forecast_service.generate_and_save_forecast(product_id, horizon=horizon)
    else:
        data = forecast_service.get_forecast(product_id)

    return format_response(
        data=data,
        message=f"Forecast for SKU '{data.get('sku')}' retrieved successfully.",
        status_code=200
    )


@forecasts_bp.route("/api/forecasts/<int:product_id>/train", methods=["POST"])
def retrain_product_forecast(product_id: int):
    """Triggers an on-demand re-benchmarking and champion selection pipeline for a SKU."""
    horizon = request.args.get("horizon", default=14, type=int)
    data = forecast_service.generate_and_save_forecast(product_id, horizon=horizon)

    return format_response(
        data=data,
        message=f"Model re-benchmarking complete. Champion selected: '{data['champion_model']}'.",
        status_code=200
    )


@forecasts_bp.route("/api/forecasts/models/health", methods=["GET"])
def get_model_health():
    """
    Model Health Observability Screen (Spec §36).
    Exposes model versions, champion distribution, accuracy benchmarks, and data drift telemetry.
    """
    health_data = forecast_service.get_model_health_overview()
    return format_response(
        data=health_data,
        message="Model health telemetry retrieved successfully.",
        status_code=200
    )
