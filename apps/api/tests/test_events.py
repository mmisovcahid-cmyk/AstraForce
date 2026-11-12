import numpy as np
import pandas as pd

from app.harmonize.events import cluster_events, summarize

# ~0.009° enlem ≈ 1 km
KM = 0.009


def _cluster(points, **kw):
    pts = sorted(points)
    day = np.array([p[0] for p in pts])
    lat = np.array([p[1] for p in pts])
    lon = np.array([p[2] for p in pts])
    return cluster_events(day, lat, lon, **kw)


def test_neighbouring_pixels_same_day_are_one_event():
    labels = _cluster([(0, 40.0, 45.0), (0, 40.0 + 0.4 * KM, 45.0), (0, 40.0 + 0.8 * KM, 45.0)])
    assert len(set(labels)) == 1


def test_points_beyond_eps_are_separate():
    labels = _cluster([(0, 40.0, 45.0), (0, 40.0 + 2.0 * KM, 45.0)], eps_km=1.5)
    assert len(set(labels)) == 2


def test_consecutive_days_link_but_two_day_gap_does_not():
    linked = _cluster([(0, 40.0, 45.0), (1, 40.0, 45.0)], eps_days=1)
    gap = _cluster([(0, 40.0, 45.0), (2, 40.0, 45.0)], eps_days=1)
    assert len(set(linked)) == 1
    assert len(set(gap)) == 2


def test_chain_merges_transitively_and_across_chunks():
    # Her gün 1 km kuzeye ilerleyen tek bir yangın; dilim sınırı 3 günde bir.
    pts = [(d, 40.0 + d * KM, 45.0) for d in range(10)]
    assert len(set(_cluster(pts, chunk_days=3))) == 1


def test_bridge_point_merges_two_old_events_in_a_later_chunk():
    # Gün 0'da iki ayrı yangın (3 km), gün 1'de aralarında ikisine de yakın iki nokta.
    pts = [
        (0, 40.0, 45.0),
        (0, 40.0 + 3 * KM, 45.0),
        (1, 40.0 + 1.0 * KM, 45.0),
        (1, 40.0 + 2.0 * KM, 45.0),
    ]
    assert len(set(_cluster(pts, chunk_days=1))) == 1


def test_labels_are_compact_and_ordered_input_required():
    labels = _cluster([(0, 10.0, 10.0), (0, 20.0, 20.0), (5, 30.0, 30.0)])
    assert sorted(set(labels)) == [0, 1, 2]
    try:
        cluster_events(np.array([1, 0]), np.array([0.0, 0.0]), np.array([0.0, 0.0]))
    except ValueError:
        pass
    else:
        raise AssertionError("sırasız girdi reddedilmeliydi")


def test_summarize_counts_event_days_not_pixels():
    df = pd.DataFrame(
        {
            "d": [0, 0, 0, 1],
            "lat": [40.0, 40.001, 41.0, 40.0],
            "lon": [45.0, 45.0, 45.0, 45.0],
            "frp": [1.0, 2.0, 3.0, 4.0],
            "h3": [7, 7, 7, 7],
            "nrt": [0, 0, 1, 0],
        }
    )
    labels = np.array([0, 0, 1, 0])
    events, daily = summarize(df, labels)
    assert len(events) == 2
    day0 = daily[daily.d == 0].iloc[0]
    assert (day0.n_det, day0.n_evt, day0.frp_sum, day0.has_nrt) == (3, 2, 6.0, 1)
