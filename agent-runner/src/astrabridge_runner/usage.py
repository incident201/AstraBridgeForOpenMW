"""Provider-reported usage, separate from the runner's context estimates.

Output includes reasoning. Cache/reasoning are subsets, not extra tokens.
Missing counters stay unknown; sums include only reported or derivable values.
"""
import copy
import json
from pathlib import Path


FIELDS = ('input_tokens', 'cached_input_tokens', 'uncached_input_tokens',
          'output_tokens', 'reasoning_tokens', 'total_tokens')


def counter(data, *paths):
    for path in paths:
        value = data
        for key in path.split('.'):
            value = value.get(key) if isinstance(value, dict) else None
        if type(value) is int and value >= 0:
            return value
    return None


def normalize(usage):
    usage = usage if isinstance(usage, dict) else {}
    incoming = counter(usage, 'input_tokens', 'total_input_tokens', 'prompt_tokens')
    cached = counter(usage, 'input_tokens_details.cached_tokens', 'total_cached_tokens',
                     'prompt_cache_hit_tokens', 'prompt_tokens_details.cached_tokens')
    reasoning = counter(usage, 'output_tokens_details.reasoning_tokens', 'total_thought_tokens',
                        'reasoning_tokens', 'completion_tokens_details.reasoning_tokens')
    outgoing = counter(usage, 'output_tokens')
    total = counter(usage, 'total_tokens')
    if outgoing is None:
        if 'total_output_tokens' in usage:  # Google reports thoughts separately.
            visible = counter(usage, 'total_output_tokens')
            if visible is not None and reasoning is not None:
                outgoing = visible + reasoning
        elif 'completion_tokens' in usage:
            outgoing = counter(usage, 'completion_tokens')
            # xAI's legacy top-level reasoning_tokens is separate; nested
            # completion_tokens_details in other APIs is already included.
            if outgoing is not None and counter(usage, 'reasoning_tokens') is not None:
                outgoing += usage['reasoning_tokens']
        if total is not None and incoming is not None and total >= incoming:
            outgoing = max(outgoing or 0, total - incoming)
    if total is None and incoming is not None and outgoing is not None:
        total = incoming + outgoing
    uncached = incoming - cached if incoming is not None and cached is not None and cached <= incoming else None
    if incoming is not None and cached is not None and cached > incoming:
        cached = None  # Preserve the inconsistent provider fields in the raw log.
    return dict(zip(FIELDS, (incoming, cached, uncached, outgoing, reasoning, total)))


def bucket():
    return {'requests': 0, 'failed_requests': 0, 'requests_without_usage': 0,
            'tokens': {name: 0 for name in FIELDS},
            'reported_requests': {name: 0 for name in FIELDS},
            'cache_reported_input_tokens': 0, 'cache_hits': 0}


def add(target, record):
    target['requests'] += 1
    target['failed_requests'] += int(record.get('outcome') != 'completed')
    values = record['tokens']
    target['requests_without_usage'] += int(all(value is None for value in values.values()))
    for name, value in values.items():
        if value is not None:
            target['tokens'][name] += value
            target['reported_requests'][name] += 1
    if values['input_tokens'] is not None and values['cached_input_tokens'] is not None:
        target['cache_reported_input_tokens'] += values['input_tokens']
        target['cache_hits'] += values['cached_input_tokens']


def display_bucket(target):
    target = copy.deepcopy(target)
    for name in FIELDS:
        if not target['reported_requests'][name]:
            target['tokens'][name] = None
    denominator = target.pop('cache_reported_input_tokens')
    hits = target.pop('cache_hits')
    target['cache_ratio'] = hits / denominator if denominator else None
    target['cache_ratio_input_tokens'] = denominator
    return target


class Usage:
    def __init__(self):
        self.total = bucket()
        self.by_purpose = {}
        self.last = None
        self.seen = set()

    def accept(self, event):
        if event.get('kind') != 'api_response':
            return False
        purpose = event.get('purpose')
        # Earlier journals recorded usage without classifying compaction.
        if purpose not in ('inference', 'checkpoint'):
            if not event.get('usage'):
                return False
            purpose = 'unclassified'
        index = event['index']
        if index in self.seen:
            return False
        self.seen.add(index)
        status = event.get('status')
        outcome = event.get('outcome') or ('completed' if status and 200 <= status < 300 else 'failed')
        record = {'index': index, 'purpose': purpose, 'outcome': outcome,
                  'tokens': normalize(event.get('usage'))}
        add(self.total, record)
        add(self.by_purpose.setdefault(purpose, bucket()), record)
        self.last = record
        return True

    def snapshot(self):
        return {'schema': 1, 'total': display_bucket(self.total),
                'by_purpose': {key: display_bucket(value) for key, value in self.by_purpose.items()},
                'last_request': copy.deepcopy(self.last)}


def read_usage(session):
    usage = Usage()
    with (Path(session) / 'events.jsonl').open('rb') as stream:
        for line in stream:
            if not line.endswith(b'\n'):
                break  # An active writer or a crash may leave the last line partial.
            usage.accept(json.loads(line))
    return usage.snapshot()


def format_usage(snapshot):
    def number(value):
        return f'{value:,}' if value is not None else '?'
    def counts(values):
        return (f"in {number(values['input_tokens'])}, cache {number(values['cached_input_tokens'])}, "
                f"uncached {number(values['uncached_input_tokens'])}, "
                f"out {number(values['output_tokens'])} (reasoning {number(values['reasoning_tokens'])}), "
                f"total {number(values['total_tokens'])}")
    total = snapshot['total']
    ratio = total['cache_ratio']
    cache = f'{ratio:.1%}' if ratio is not None else 'unknown'
    last = snapshot['last_request']
    line = f"Last API [{last['purpose']}]: {counts(last['tokens'])}. " if last else ''
    partial = any(0 < count < total['requests'] for count in total['reported_requests'].values())
    return (line + f"Session ({total['requests']} requests, {total['failed_requests']} failed): "
            f"{counts(total['tokens'])}; cache hit {cache}."
            + (' Totals include only reported counters.' if partial else ''))
