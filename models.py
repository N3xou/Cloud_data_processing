from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.sql import func
from db import Base

class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, index=True)
    prediction = Column(String)
    probabilities = Column(String)
    confidence = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<Prediction(id={self.id}, prediction={self.prediction}, confidence={self.confidence})>"


class ExternalApiCall(Base):
    """
    New table to store results from external API calls
    Designed for load testing and performance analysis
    """
    __tablename__ = "external_api_calls"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String(36), unique=True, index=True)  # UUID for tracking
    external_url = Column(String(512))
    http_method = Column(String(10))
    http_version = Column(String(10))  # HTTP/1.1 or HTTP/2

    # Response data (compact)
    status_code = Column(Integer)
    response_summary = Column(Text)  # Compact JSON summary
    is_success = Column(Boolean, default=True)

    # Performance metrics
    request_duration_ms = Column(Float)
    external_api_duration_ms = Column(Float)
    db_write_duration_ms = Column(Float)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<ExternalApiCall(id={self.id}, status={self.status_code}, duration={self.request_duration_ms}ms)>"