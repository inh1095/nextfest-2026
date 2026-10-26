"""Typed, scoped observations from Steam's public StoreBrowse item summaries.

These are store-filtered reviews and KR purchase offers, never wishlist totals.
No network or production writes happen in this module.
"""
import json
import math
import re
from urllib.parse import urlencode

from collect import parse

ENDPOINT = 'https://api.steampowered.com/IStoreBrowseService/GetItems/v1/'
METRICS = ('review_count', 'review_positive_percent', 'price_final')
ALL_METRICS = (*METRICS, 'followers')


def enabled(config):
    value = config['collection'].get('metadata_enabled', False)
    if type(value) is not bool:
        raise ValueError('metadata_enabled_must_be_boolean')
    return value


def request_limit(config, catalog, mode=None, full=False):
    mode = mode or config['collection'].get('default_mode', 'both')
    if not enabled(config) or mode not in ('both', 'metadata'):
        return 0
    value = (math.ceil(len(catalog['games']) / 100) * 2 if full else
             config['collection'].get('metadata_request_budget', 100))
    if type(value) is not int or value < 0:
        raise ValueError('invalid_metadata_budget')
    return value


def target_interval(config, catalog):
    if not enabled(config):
        return None
    settings = config['collection']
    budget = request_limit(config, catalog, 'metadata')
    if not budget:
        return None
    minimum = settings.get('metadata_interval_minutes', 240)
    if type(minimum) is not int or minimum < settings['interval_minutes']:
        raise ValueError('invalid_metadata_interval')
    return max(minimum, math.ceil(math.ceil(len(catalog['games']) / 100) / budget) *
               settings['interval_minutes'])


def request_url(games):
    query = {'ids': [{'appid': g['app_id']} for g in games],
             'context': {'language': 'koreana', 'country_code': 'KR'},
             'data_request': {'include_reviews': True, 'include_release': True}}
    return ENDPOINT + '?' + urlencode({'input_json': json.dumps(query, separators=(',', ':'))})


def response_items(data, games):
    items = data.get('response', {}).get('store_items')
    if not isinstance(items, list):
        raise ValueError('invalid_store_response')
    expected = {g['app_id'] for g in games}
    result = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('invalid_store_item')
        app = item.get('id')
        if type(app) is not int or app not in expected or app in result:
            raise ValueError('store_response_mapping_mismatch')
        if type(item.get('item_type')) is not int or item['item_type'] != 0:
            raise ValueError('store_response_mapping_mismatch')
        success, returned_app = item.get('success'), item.get('appid')
        if type(success) is not int or success < 0:
            raise ValueError('invalid_store_result')
        if success == 1:
            if type(returned_app) is not int or returned_app != app:
                raise ValueError('store_response_mapping_mismatch')
        elif returned_app is not None and (type(returned_app) is not int or returned_app not in (0, app)):
            # Failed items may anonymize appid to zero, but id still has to be the requested app.
            raise ValueError('store_response_mapping_mismatch')
        result[app] = item
    # Missing items are explicit errors for their own game, not a fabricated zero.
    return result


def retryable_failure(samples):
    """Only a complete latest, same-time three-metric error batch can bypass the TTL."""
    latest = {}
    for sample in samples:
        key = sample['metric']
        if key in METRICS and (key not in latest or sample['observed_at'] > latest[key]['observed_at']):
            latest[key] = sample
    return (set(latest) == set(METRICS) and
            all(s['status'] == 'error' for s in latest.values()) and
            len({s['observed_at'] for s in latest.values()}) == 1)


def integer(value):
    if type(value) is not int or not 0 <= value <= 9007199254740991:
        raise ValueError('invalid_store_number')
    return value


def cents(value):
    if isinstance(value, str) and re.fullmatch(r'\d+', value):
        value = int(value)
    return integer(value)


def base_context(game):
    return {'app_id': game['app_id'], 'app_scope': 'base',
            'country': 'KR', 'language': 'koreana'}


def observations(game, item, at, *, error=None, batch_size=1):
    context = base_context(game)
    context['batch_size'] = batch_size
    result = []
    for metric in METRICS:
        ctx = dict(context)
        if metric.startswith('review_'):
            ctx.update(review_scope='store_summary_filtered',
                       percentage_precision='source_rounded_integer')
        else:
            ctx.update(currency=None, divisor=100, initial=None, discount_percent=None,
                       is_free=None, formatted_final_price=None)
        sample = {'game_id': game['id'], 'metric': metric, 'observed_at': at,
                  'status': 'unavailable', 'value': None, 'source_url': ENDPOINT,
                  'context': ctx, 'error_code': None}
        result.append(sample)
        if error or item is None:
            sample.update(status='error', error_code=error or 'store_item_missing')
            continue
        if type(item.get('success')) is not int or item['success'] != 1:
            ctx['store_item_success'] = item.get('success')
            sample['error_code'] = 'store_item_unavailable'
            continue
        try:
            if metric.startswith('review_'):
                review = item.get('reviews', {}).get('summary_filtered')
                if not isinstance(review, dict):
                    sample['error_code'] = 'review_summary_missing'
                    continue
                count = integer(review.get('review_count'))
                ctx['review_score_label'] = review.get('review_score_label')
                if metric == 'review_count':
                    value = count
                elif count == 0:
                    sample['error_code'] = 'no_reviews'
                    continue
                else:
                    value = integer(review.get('percent_positive'))
                    if value > 100:
                        raise ValueError('invalid_review_percentage')
            else:
                free = item.get('is_free', False)
                if type(free) is not bool:
                    raise ValueError('invalid_free_flag')
                ctx['is_free'] = free
                ctx['is_free_field_present'] = 'is_free' in item
                ctx['is_coming_soon'] = item.get('is_coming_soon', False)
                ctx['is_coming_soon_field_present'] = 'is_coming_soon' in item
                offer = item.get('best_purchase_option')
                if free:
                    value = 0
                    ctx['currency'] = 'KRW'
                elif not isinstance(offer, dict) or 'final_price_in_cents' not in offer:
                    sample['error_code'] = ('price_not_announced' if ctx['is_coming_soon'] else
                                            'price_not_offered')
                    continue
                else:
                    ctx['package_id'] = offer.get('packageid')
                    ctx['purchase_option_name'] = offer.get('purchase_option_name')
                    ctx['included_game_count'] = offer.get('included_game_count')
                    ctx['must_purchase_as_set'] = offer.get('must_purchase_as_set')
                    if type(ctx['included_game_count']) is not int or ctx['included_game_count'] != 1:
                        sample['error_code'] = 'single_game_price_unverified'
                        continue
                    # Country alone does not prove currency. Verify the displayed denomination.
                    formatted = offer.get('formatted_final_price')
                    ctx['formatted_final_price'] = formatted
                    if not isinstance(formatted, str) or not re.search(r'₩|원', formatted):
                        sample['error_code'] = 'price_currency_unverified'
                        continue
                    value = cents(offer['final_price_in_cents'])
                    shown = re.sub(r'[^\d.]', '', formatted)
                    if not re.fullmatch(r'\d+(?:\.\d+)?', shown) or float(shown) * 100 != value:
                        raise ValueError('price_display_scale_mismatch')
                    ctx['currency'] = 'KRW'
                    if 'original_price_in_cents' in offer:
                        ctx['initial'] = cents(offer['original_price_in_cents'])
                    if 'discount_pct' in offer:
                        discount = integer(offer['discount_pct'])
                        if discount > 100:
                            raise ValueError('invalid_discount_percentage')
                        ctx['discount_percent'] = discount
            sample.update(status='ok', value=value)
            validate_sample(sample, game)
        except (ValueError, TypeError, AttributeError, OverflowError):
            sample.update(status='error', value=None, error_code='invalid_store_metric')
    return result


def summaries(samples, config, catalog, game, end):
    interval = target_interval(config, catalog)
    result = {}
    for metric in ALL_METRICS:
        rows = sorted((s for s in samples if s['metric'] == metric and parse(s['observed_at']) <= end),
                      key=lambda s: s['observed_at'])
        good = [s for s in rows if s['status'] == 'ok']
        last, latest = (rows[-1] if rows else None), (good[-1] if good else None)
        current_context = (latest or last or {}).get('context', base_context(game))
        result[metric] = {
            'status': last['status'] if last else ('pending' if enabled(config) and metric != 'followers'
                                                 else 'unavailable'),
            'current': latest['value'] if latest else None,
            'last_ok_at': latest['observed_at'] if latest else None,
            'last_attempt_at': last['observed_at'] if last else None,
            'last_error_code': last.get('error_code') if last else (
                'verified_source_unavailable' if metric == 'followers' else None),
            'target_interval_minutes': interval if metric != 'followers' else None,
            'context': current_context, 'observation_count': len(rows)}
    return result


def validate_sample(sample, game=None):
    if sample['metric'] not in METRICS:
        raise ValueError('unsupported_store_metric')
    if sample['source_url'] != ENDPOINT:
        raise ValueError('store_source_mismatch')
    if sample['status'] == 'ok':
        integer(sample['value'])
    ctx = sample.get('context', {})
    if (type(ctx.get('app_id')) is not int or ctx['app_id'] <= 0 or
            ctx.get('app_scope') != 'base' or ctx.get('country') != 'KR' or
            ctx.get('language') != 'koreana' or
            (game and ctx['app_id'] != game['app_id'])):
        raise ValueError('store_context_mismatch')
    if sample['metric'].startswith('review_'):
        if ctx.get('review_scope') != 'store_summary_filtered':
            raise ValueError('review_scope_mismatch')
        if sample['status'] == 'ok' and sample['metric'] == 'review_positive_percent' and sample['value'] > 100:
            raise ValueError('invalid_review_percentage')
    elif sample['status'] == 'ok':
        if ctx.get('currency') != 'KRW' or type(ctx.get('divisor')) is not int or ctx['divisor'] != 100:
            raise ValueError('price_unit_mismatch')
        if type(ctx.get('is_free')) is not bool or (ctx['is_free'] and sample['value'] != 0):
            raise ValueError('price_free_mismatch')
        if not ctx['is_free']:
            if type(ctx.get('included_game_count')) is not int or ctx['included_game_count'] != 1:
                raise ValueError('single_game_price_unverified')
            formatted = ctx.get('formatted_final_price')
            if not isinstance(formatted, str) or not re.search(r'₩|원', formatted):
                raise ValueError('price_currency_unverified')
            shown = re.sub(r'[^\d.]', '', formatted)
            if not re.fullmatch(r'\d+(?:\.\d+)?', shown) or float(shown) * 100 != sample['value']:
                raise ValueError('price_display_scale_mismatch')
        if ctx.get('initial') is not None:
            integer(ctx['initial'])
            if ctx['initial'] < sample['value']:
                raise ValueError('price_initial_below_final')
        if ctx.get('discount_percent') is not None:
            integer(ctx['discount_percent'])
            if ctx['discount_percent'] > 100:
                raise ValueError('invalid_discount_percentage')
