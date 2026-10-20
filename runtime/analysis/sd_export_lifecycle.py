"""Publish a final SD result only after verified flush cancellation/owner recovery."""
from sd_flush_barrier import cancel_resume, quiesce


def export_with_flush_lifecycle(export_once, serial, sequence, publish_report):
    """export_once(quiesce_callback) runs existing export_card; publisher is atomic.

    Return only after cleanup AND report publication. No return inside try/finally:
    a successful card copy must not hide a failed owner recovery.
    """
    result = dict(ok=False, error="export interrupted", sequence=sequence)
    try:
        result = dict(export_once(lambda: quiesce(serial, sequence)))
        result['sequence'] = sequence
    except Exception as error:
        result.update(ok=False, error=f'{type(error).__name__}: {error}')
    finally:
        try:
            result['flush_lifecycle'] = cancel_resume(serial, sequence)
        except Exception as error:
            result['flush_lifecycle'] = dict(ok=False, error=f'{type(error).__name__}: {error}')
            result['export_data_ok'] = bool(result.get('ok'))
            result['ok'] = False
            result['error'] = (result.get('error', '') + '; flush owner recovery failed: ' +
                               result['flush_lifecycle']['error']).lstrip('; ')
        # export_card leaves the overall report false while owner recovery is pending.
        # A publisher failure raises to the controller; no success may be returned.
        publish_report(result)
    return result
