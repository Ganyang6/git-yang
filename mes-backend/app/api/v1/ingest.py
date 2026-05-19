"""
Segment ingestion API routes.

Endpoints:
  POST /api/v1/ingest/frame   - feed a single pose frame for classification
  POST /api/v1/ingest/frames  - feed a batch of pose frames
  POST /api/v1/ingest/flush   - flush open segments (end of shift)
  GET  /api/v1/ingest/stats   - pipeline statistics
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.models.database import get_session
from app.models.schemas import (
    ApiResponse,
    ClassificationResultSchema,
    PoseFrameSchema,
)
from app.services.process_segmenter import ActionPipeline, SegmentEvent
from app.services.worktime_aggregator import save_segment, aggregate_segments
from app.api.deps import get_db_session, require_auth, require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ingest", tags=["ingest"])

# Module-level pipeline (singleton per process)
_pipeline: Optional[ActionPipeline] = None

# Lazy aggregation state: track unaggregated segment count per station
_pending_aggregations: Dict[str, int] = {}
# Threshold: trigger aggregate_segments after this many unaggregated segments
_AGGREGATION_THRESHOLD = 5

# Maximum frames per batch request (P1 #36)
_MAX_BATCH_FRAMES = 500


def _get_pipeline() -> ActionPipeline:
    """Get or create the singleton action pipeline."""
    global _pipeline
    if _pipeline is None:
        from app.core.config import load_app_config
        cfg = load_app_config()
        _pipeline = ActionPipeline(
            window_size=cfg.action_classifier.window_size,
            min_landmark_visibility=cfg.action_classifier.min_landmark_visibility,
            confirmation_frames=cfg.process_segmenter.confirmation_frames,
            idle_timeout_frames=cfg.process_segmenter.idle_timeout_frames,
            max_segment_duration_s=cfg.process_segmenter.max_segment_duration_s,
        )
        logger.info(
            "Action pipeline created: window=%d, confirm=%d, idle_timeout=%d",
            cfg.action_classifier.window_size,
            cfg.process_segmenter.confirmation_frames,
            cfg.process_segmenter.idle_timeout_frames,
        )
    return _pipeline




@router.post("/frame")
def ingest_frame(
    frame: PoseFrameSchema,
    station_id: str = Query("default"),
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_admin),
):
    """
    Feed a single pose frame into the classification pipeline.

    If the internal state machine closes a segment, the segment is
    persisted to SQLite automatically.  Aggregation is triggered
    after every 5 unaggregated segments (lazy aggregation).
    """
    pipeline = _get_pipeline()
    event = pipeline.process_frame(frame, station_id)

    result = {
        "accepted": True,
        "segment_closed": False,
        "pipeline_stats": pipeline.stats,
    }

    if event:
        save_segment(session, event)
        result["segment_closed"] = True
        result["segment"] = {
            "action": event.action.value,
            "station_id": event.station_id,
            "duration_ms": round(event.duration_ms, 1),
            "confidence": round(event.confidence, 3),
        }

        # Lazy aggregation: trigger after threshold segments
        pending = _pending_aggregations.get(station_id, 0) + 1
        if pending >= _AGGREGATION_THRESHOLD:
            aggregate_segments(session, station_id)
            _pending_aggregations[station_id] = 0
            logger.debug(
                "Triggered aggregation for station %s after %d segments",
                station_id, pending,
            )
        else:
            _pending_aggregations[station_id] = pending

    return ApiResponse(data=result, timestamp=time.time())


@router.post("/frames")
def ingest_frames(
    frames: List[PoseFrameSchema],
    station_id: str = Query("default"),
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_admin),
):
    """
    Feed a batch of pose frames.  Useful for playback or bulk import.
    Maximum 500 frames per request.
    """
    if len(frames) > _MAX_BATCH_FRAMES:
        raise HTTPException(
            status_code=400,
            detail=f"Too many frames: {len(frames)}, maximum is {_MAX_BATCH_FRAMES} per request",
        )

    pipeline = _get_pipeline()
    segments_closed = []

    for frame in frames:
        event = pipeline.process_frame(frame, station_id)
        if event:
            save_segment(session, event)
            segments_closed.append({
                "action": event.action.value,
                "duration_ms": round(event.duration_ms, 1),
                "confidence": round(event.confidence, 3),
            })

    if segments_closed:
        aggregate_segments(session, station_id)
        _pending_aggregations[station_id] = 0

    return ApiResponse(
        data={
            "accepted": len(frames),
            "segments_closed": len(segments_closed),
            "segments": segments_closed,
            "pipeline_stats": pipeline.stats,
        },
        timestamp=time.time(),
    )


@router.post("/flush")
def flush_segments(
    station_id: str = Query("default"),
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_admin),
):
    """Flush all open segments.  Call at end of shift or on shutdown."""
    pipeline = _get_pipeline()
    events = pipeline.flush_all(station_id)

    flushed = []
    for event in events:
        save_segment(session, event)
        flushed.append({
            "action": event.action.value,
            "duration_ms": round(event.duration_ms, 1),
        })

    if flushed:
        aggregate_segments(session, station_id)
        _pending_aggregations[station_id] = 0

    return ApiResponse(
        data={
            "flushed": len(flushed),
            "segments": flushed,
            "pipeline_stats": pipeline.stats,
        },
        timestamp=time.time(),
    )


@router.get("/stats")
def get_pipeline_stats(_user: dict = Depends(require_auth)):
    """Get current pipeline statistics."""
    pipeline = _get_pipeline()
    return ApiResponse(data=pipeline.stats, timestamp=time.time())
