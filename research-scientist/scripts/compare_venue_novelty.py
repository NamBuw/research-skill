#!/usr/bin/env python3
"""Compare claim-level novelty with a documented same-track accepted-paper panel.

Scores are reviewer judgments supplied with source locators. Arithmetic does
not establish novelty, venue standards, fit, acceptance odds or paper quality.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import re
import statistics
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from compare_scorecards import _snapshot_is_blocked, index_sources_dir, verify_locator
from venue_leads import load_venue_quality_refs, lookup_venue_quality

AXES = ('scope_audience', 'contribution_track', 'evidence_maturity',
        'format_eligibility', 'user_constraints')
HARD_CONSTRAINTS = ('deadline', 'budget', 'eligibility')
_DNS_LABEL_RE = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$')


def _filled(value):
    return isinstance(value, str) and bool(value.strip())


def _valid_hostname(host, netloc=''):
    if not host:
        return False
    if netloc.startswith('['):
        try:
            return ipaddress.ip_address(host).version == 6
        except ValueError:
            return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    try:
        ascii_host = host.encode('idna').decode('ascii')
    except UnicodeError:
        return False
    if not ascii_host or len(ascii_host) > 253:
        return False
    labels = ascii_host.split('.')
    if any(not lbl or not _DNS_LABEL_RE.match(lbl) for lbl in labels):
        return False
    if labels[-1].isdigit():
        return False
    return True


def _https(value):
    if not _filled(value):
        return False
    if any(ch.isspace() or unicodedata.category(ch) in {'Cc', 'Cf'} for ch in value):
        return False
    try:
        parsed = urlparse(value)
        port = parsed.port
        if parsed.scheme != 'https':
            return False
        netloc = parsed.netloc or ''
        if '@' in netloc or parsed.username is not None or parsed.password is not None:
            return False
        if port is not None and port < 1:
            return False
        return _valid_hostname(parsed.hostname, netloc)
    except ValueError:
        return False


def _time(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.utcoffset() is not None
    except ValueError:
        return False


def _check_rating(item, prefix, errors):
    for field in ('id', 'claim', 'closest_work_id', 'closest_work_locator',
                  'contribution_delta', 'search_manifest', 'score_reason', 'assessment_boundary',
                  'contribution_type'):
        if not _filled(item.get(field)):
            errors.append(f'{prefix}:missing_or_blank:{field}')
    if not _time(item.get('assessed_at_utc')):
        errors.append(f'{prefix}:assessed_at_utc_must_have_timezone')
    if item.get('reading_basis') != 'full_text':
        errors.append(f'{prefix}:full_text_required_for_novelty_comparison')
    for field in ('score', 'low', 'high'):
        value = item.get(field)
        if type(value) is not int or not 0 <= value <= 10:
            errors.append(f'{prefix}:invalid_{field}')
    if all(type(item.get(k)) is int for k in ('score', 'low', 'high')) and not (
            0 <= item['low'] <= item['score'] <= item['high'] <= 10):
        errors.append(f'{prefix}:score_outside_interval')


def check(profile, as_of=None, sources_dir=None, quality_refs_dir=None):
    if not isinstance(profile, dict):
        raise ValueError('profile must be an object')
    errors, warnings = [], []
    as_of = as_of or datetime.now(timezone.utc)
    if as_of.utcoffset() is None:
        raise ValueError('as_of must have timezone')

    refs = load_venue_quality_refs(quality_refs_dir)

    venue = profile.get('venue')
    if not isinstance(venue, dict):
        errors.append('venue:must_be_object')
        venue = {}
    for field in ('name', 'edition', 'track'):
        if not _filled(venue.get(field)):
            errors.append(f'venue:missing_or_blank:{field}')
    if not _https(venue.get('official_cfp_url')):
        errors.append('venue:official_cfp_url_must_be_https')
    venue_fresh = False
    if not _time(venue.get('checked_at_utc')):
        errors.append('venue:checked_at_utc_must_have_timezone')
    else:
        checked = datetime.fromisoformat(venue['checked_at_utc'].replace('Z', '+00:00'))
        max_age = venue.get('max_source_age_days', 14)
        if type(max_age) is not int or max_age < 0:
            errors.append('venue:max_source_age_days_invalid')
        else:
            age = (as_of - checked).total_seconds() / 86400
            venue_fresh = 0 <= age <= max_age
            if not venue_fresh:
                warnings.append('venue:cfp_source_stale_or_future;_fit_score_withheld')

    venue_quality_context = lookup_venue_quality(venue.get('name'), refs) if _filled(venue.get('name')) else None

    target = profile.get('target')
    if not isinstance(target, dict):
        errors.append('target:must_be_object')
        target = {}
    _check_rating(target, 'target', errors)
    if _time(target.get('assessed_at_utc')) and datetime.fromisoformat(target['assessed_at_utc'].replace('Z', '+00:00')) > as_of:
        errors.append('target:assessment_time_in_future')

    selection = profile.get('panel_selection')
    if not isinstance(selection, dict):
        errors.append('panel_selection:must_be_object')
        selection = {}
    for field in ('search_manifest', 'inclusion_rule', 'exclusion_log', 'date_window',
                  'rubric_version', 'calibration_notes', 'selection_bias'):
        if not _filled(selection.get(field)):
            errors.append(f'panel_selection:missing_or_blank:{field}')
    screened = selection.get('screened_count')
    if type(screened) is not int or screened < 0:
        errors.append('panel_selection:invalid_screened_count')

    panel = profile.get('accepted_panel')
    if not isinstance(panel, list):
        errors.append('accepted_panel:must_be_list')
        panel = []
    if len(panel) < 5:
        warnings.append('accepted_panel:fewer_than_five_comparable_papers; distribution_not_reported')
    if type(screened) is int and screened < len(panel):
        errors.append('panel_selection:screened_count_less_than_included')
    ids = set()
    for index, item in enumerate(panel):
        prefix = f'accepted_panel:{index}'
        if not isinstance(item, dict):
            errors.append(f'{prefix}:must_be_object')
            continue
        _check_rating(item, prefix, errors)
        if _filled(item.get('contribution_type')) and _filled(target.get('contribution_type')) and \
                item['contribution_type'] != target['contribution_type']:
            errors.append(f'{prefix}:contribution_type_mismatch')
        if _time(item.get('assessed_at_utc')) and datetime.fromisoformat(item['assessed_at_utc'].replace('Z', '+00:00')) > as_of:
            errors.append(f'{prefix}:assessment_time_in_future')
        if not _https(item.get('official_acceptance_url')):
            errors.append(f'{prefix}:official_acceptance_url_must_be_https')
        if item.get('track') != venue.get('track'):
            errors.append(f'{prefix}:track_mismatch')
        if type(item.get('year')) is not int or not 1900 <= item['year'] <= as_of.year:
            errors.append(f'{prefix}:invalid_year')
        if _filled(item.get('id')) and item['id'] in ids:
            errors.append(f'{prefix}:duplicate_id')
        if _filled(item.get('id')):
            ids.add(item['id'])

    axes = profile.get('fit_axes')
    if not isinstance(axes, list):
        errors.append('fit_axes:must_be_list')
        axes = []
    axis_map = {}
    for index, item in enumerate(axes):
        prefix = f'fit_axes:{index}'
        if not isinstance(item, dict):
            errors.append(f'{prefix}:must_be_object')
            continue
        name = item.get('name')
        if not isinstance(name, str) or name not in AXES or name in axis_map:
            errors.append(f'{prefix}:invalid_or_duplicate_axis')
            continue
        axis_map[name] = item
        if type(item.get('score')) is not int or not 0 <= item['score'] <= 2:
            errors.append(f'{prefix}:score_must_be_0_to_2')
        if not _https(item.get('source_url')) or not _filled(item.get('locator')) or not _filled(item.get('reason')):
            errors.append(f'{prefix}:source_locator_and_reason_required')
    if set(axis_map) != set(AXES):
        errors.append('fit_axes:all_five_axes_required')

    constraints = profile.get('hard_constraints')
    if not isinstance(constraints, list):
        errors.append('hard_constraints:must_be_list')
        constraints = []
    constraint_map = {}
    for index, item in enumerate(constraints):
        prefix = f'hard_constraints:{index}'
        if not isinstance(item, dict):
            errors.append(f'{prefix}:must_be_object')
            continue
        name = item.get('name')
        if not isinstance(name, str) or name not in HARD_CONSTRAINTS or name in constraint_map:
            errors.append(f'{prefix}:invalid_or_duplicate_constraint')
            continue
        constraint_map[name] = item
        if item.get('status') not in ('met', 'failed', 'unverified'):
            errors.append(f'{prefix}:invalid_status')
        if not _filled(item.get('reason')):
            errors.append(f'{prefix}:reason_required')
        if item.get('status') in ('met', 'failed') and not _https(item.get('source_url')):
            errors.append(f'{prefix}:verified_status_needs_source_url')
    if set(constraint_map) != set(HARD_CONSTRAINTS):
        errors.append('hard_constraints:deadline_budget_eligibility_required')

    locator_verification = None
    if sources_dir is not None:
        source_index = index_sources_dir(sources_dir)
        checked = 0
        verified = 0
        failed = 0

        if _filled(target.get('closest_work_locator')):
            checked += 1
            ok, reason = verify_locator(
                target['closest_work_locator'],
                source_index,
                default_source_ids=(target.get('closest_work_id'), target.get('id')),
                extra_quotes=(target.get('closest_work_quote'), target.get('quote')),
            )
            if ok:
                verified += 1
            else:
                failed += 1
                errors.append(f'target:closest_work_locator_unverified:{reason}')

        for index, item in enumerate(panel):
            if not isinstance(item, dict) or not _filled(item.get('closest_work_locator')):
                continue
            checked += 1
            ok, reason = verify_locator(
                item['closest_work_locator'],
                source_index,
                default_source_ids=(item.get('closest_work_id'), item.get('id')),
                extra_quotes=(item.get('closest_work_quote'), item.get('quote')),
            )
            if ok:
                verified += 1
            else:
                failed += 1
                errors.append(f'accepted_panel:{index}:closest_work_locator_unverified:{reason}')

        for index, item in enumerate(axes):
            if not isinstance(item, dict) or not _filled(item.get('locator')):
                continue
            checked += 1
            ok, reason = verify_locator(
                item['locator'],
                source_index,
                source_url=item.get('source_url'),
                extra_quotes=(item.get('quote'),),
                require_url_snapshot=True,
            )
            if ok:
                verified += 1
            else:
                failed += 1
                errors.append(f'fit_axes:{index}:locator_unverified:{reason}')

        for index, item in enumerate(constraints):
            if not isinstance(item, dict) or item.get('status') not in ('met', 'failed'):
                continue
            url = item.get('source_url')
            if not _https(url):
                continue
            if url not in source_index['venue_snapshots']:
                errors.append(f'hard_constraints:{index}:source_snapshot_missing')
            elif _snapshot_is_blocked(source_index['venue_snapshots'][url]):
                errors.append(f'hard_constraints:{index}:unverified_or_stale_venue_snapshot')

        locator_verification = {
            'sources_dir': str(source_index['root']),
            'sources_indexed': source_index['sources_indexed'],
            'skipped_files': source_index['skipped_files'],
            'checked': checked,
            'verified': verified,
            'failed': failed,
        }

    recent_panel_count = sum(type(item.get('year')) is int and item['year'] >= as_of.year - 3
                             for item in panel if isinstance(item, dict))
    if recent_panel_count < 5:
        warnings.append('accepted_panel:fewer_than_five_recent_same_track_papers; comparison_withheld')
    score_errors = any(item.startswith(('target:', 'accepted_panel:', 'venue:', 'panel_selection:')) for item in errors)
    comparison = None
    if not score_errors and len(panel) >= 5 and recent_panel_count >= 5:
        scores = [item['score'] for item in panel]
        definitely_higher = [item['id'] for item in panel if target['low'] > item['high']]
        definitely_lower = [item['id'] for item in panel if target['high'] < item['low']]
        overlaps = [item['id'] for item in panel if item['id'] not in definitely_higher + definitely_lower]
        comparison = {'target_novelty_score': target['score'],
                      'target_interval': [target['low'], target['high']],
                      'accepted_panel_size': len(panel),
                      'accepted_panel_median_score': statistics.median(scores),
                      'accepted_panel_score_range': [min(scores), max(scores)],
                      'target_definitely_higher_than_ids': definitely_higher,
                      'target_definitely_lower_than_ids': definitely_lower,
                      'overlapping_intervals_with_ids': overlaps,
                      'interpretation': 'Descriptive scores for a selected same-track panel; no venue novelty threshold or acceptance probability.'}
    hard_statuses = [item.get('status') for item in constraint_map.values()]
    fit_score = None
    if venue_fresh and not any(item.startswith(('fit_axes:', 'hard_constraints:', 'venue:')) for item in errors) and len(axis_map) == 5 and len(constraint_map) == 3:
        if all(status == 'met' for status in hard_statuses):
            fit_score = sum(item['score'] for item in axis_map.values())
        elif 'failed' in hard_statuses:
            warnings.append('venue:hard_constraint_conflict; do_not_recommend_as_feasible')
        else:
            warnings.append('venue:hard_constraint_unverified;_fit_score_withheld')
    out = {
        'status': 'invalid' if errors else 'structurally_checked',
        'errors': errors,
        'warnings': warnings,
        'fit_score_out_of_10': fit_score,
        'novelty_comparison': comparison,
        'venue_quality_context': venue_quality_context,
        'disclaimer': (
            'All novelty and fit ratings are supplied reviewer judgments. Verify original papers, '
            'closest work, official accepted-paper/CFP records, fees and constraints. A venue has no '
            'intrinsic novelty score; a selected panel is not an acceptance threshold or probability. '
            'Advisory venue_quality_context tiers (S/A/B/C/Unknown) reflect local reference lookup only '
            'and never contribute to fit_score_out_of_10 or novelty_comparison.'
        ),
    }
    if locator_verification is not None:
        out['locator_verification'] = locator_verification
    return out


def _compact_output(result: dict, out_path: str | None = None) -> dict:
    comp = result.get('novelty_comparison')
    comp_summary = None
    if isinstance(comp, dict):
        comp_summary = {
            'target_novelty_score': comp.get('target_novelty_score'),
            'target_interval': comp.get('target_interval'),
            'accepted_panel_size': comp.get('accepted_panel_size'),
            'accepted_panel_median_score': comp.get('accepted_panel_median_score'),
            'accepted_panel_score_range': comp.get('accepted_panel_score_range'),
        }
    vqc = result.get('venue_quality_context')
    vqc_summary = None
    if isinstance(vqc, dict):
        vqc_summary = {
            'quality_tier': vqc.get('quality_tier'),
            'matched_name': vqc.get('matched_name'),
            'matched_source': vqc.get('matched_source'),
        }
    errors = result.get('errors') or []
    warnings = result.get('warnings') or []
    return {
        'compact': True,
        'status': result.get('status'),
        'fit_score_out_of_10': result.get('fit_score_out_of_10'),
        'novelty_comparison': comp_summary,
        'venue_quality_context': vqc_summary,
        'locator_verification': result.get('locator_verification'),
        'error_count': len(errors),
        'warning_count': len(warnings),
        'errors': errors[:20],
        'warnings': warnings[:20],
        'artifact_path': out_path,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile_json')
    parser.add_argument('--sources-dir', default=None, help='Optional directory of local source files (.txt, .md, .json, .pdf) for locator verification')
    parser.add_argument('--quality-refs-dir', default=None, help='Optional directory containing paper-quality-filter reference JSON files')
    parser.add_argument('--out', default=None, help='Optional output JSON file path for full report')
    parser.add_argument('--compact', action='store_true', help='Emit compact bounded summary JSON to stdout')
    args = parser.parse_args(argv)
    try:
        profile = json.loads(Path(args.profile_json).read_text(encoding='utf-8'))
        result = check(profile, sources_dir=args.sources_dir, quality_refs_dir=args.quality_refs_dir)
        full_rendered = json.dumps(result, ensure_ascii=False)
        out_str = None
        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(full_rendered + '\n', encoding='utf-8')
            out_str = str(out_path)
        if args.compact:
            print(json.dumps(_compact_output(result, out_str), ensure_ascii=False))
        else:
            print(full_rendered)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError, RuntimeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2
    return 0 if result['status'] == 'structurally_checked' else 1


if __name__ == '__main__':
    sys.exit(main())
