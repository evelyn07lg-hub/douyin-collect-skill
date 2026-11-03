"""Future-only eligibility: no automatic historical backfill into the existing document."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json


def ensure_baseline(store):
    store.execute('''CREATE TABLE IF NOT EXISTS append_baseline(
      account_id TEXT,id TEXT,likes INTEGER,setup_at TEXT,PRIMARY KEY(account_id,id))''')


def eligible(work,store,config):
    policy=config.get('append_policy')
    if not policy:return True,'no_future_only_policy'
    ensure_baseline(store)
    threshold=config['threshold']
    try:
        published=datetime.fromisoformat(str(work['published_at']).replace('Z','+00:00'))
        if published.tzinfo:published=published.astimezone(timezone(timedelta(hours=8)))
        recorded=policy.get('recorded_through', {}).get(work['account_id'])
        if recorded and published.date()>=datetime.fromisoformat(recorded).date():
            return work['likes']>threshold,'latest_since_document' if work['likes']>threshold else 'below_threshold'
        baseline=store.rows('SELECT likes FROM append_baseline WHERE account_id=? AND id=?',(work['account_id'],work['id']))
        if baseline:
            value=baseline[0]['likes']
            if value is None or value>threshold:return False,'already_qualified_before_activation'
            return work['likes']>threshold,'new_threshold_crossing' if work['likes']>threshold else 'below_threshold'
        cutoff=datetime.fromisoformat(policy['start_at'])
        if cutoff.tzinfo:cutoff=cutoff.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
        if published.replace(tzinfo=None)<cutoff:
            store.execute('INSERT OR IGNORE INTO append_baseline VALUES(?,?,?,?)',
                (work['account_id'],work['id'],work['likes'],policy['start_at']))
            return False,'older_work_requires_threshold_history'
    except (ValueError,TypeError,KeyError):return False,'publication_time_unverified'
    return work['likes']>threshold,'new_work_after_activation' if work['likes']>threshold else 'below_threshold'