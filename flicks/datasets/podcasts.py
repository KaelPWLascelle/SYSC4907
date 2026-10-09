"""Build a podcast catalogue from RSS feeds (an explicit, user-run command; docs/adr/0010-podcasts.md).

    python -m flicks.datasets.podcasts                                  # the starter feeds below
    python -m flicks.datasets.podcasts --feed https://example.com/feed.xml --feed ...
    python -m flicks.datasets.podcasts --feeds my-feeds.txt             # one URL per line, # comments

Writes ~/.flicks/catalogs/podcasts.json, with each episode as a catalogue title (kind "episode"), and
podcasts.episodes.json beside it, with each episode's show and audio URL for downloads. Only the
feed URLs are requested; nothing about you is sent. Episodes stay on the publisher's servers until
you download one in Flicks, for your own listening; Flicks never re-hosts or alters them.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
from urllib import error, parse
import xml.etree.ElementTree as ET

from ..config import DEFAULT_PODCASTS
from ..core import load_catalog
from ..net import WEB_SCHEMES, get, public_web
from ..podcasts import FORMAT, PodcastIndex, episodes_path
from .genres import PODCAST_CATEGORIES, estimate

# Long-form shows with public feeds, across subjects. Any RSS feed works with --feed.
FEEDS = (
    'https://feeds.feedburner.com/dancarlin/history?format=xml',   # Dan Carlin's Hardcore History
    'https://podcasts.files.bbci.co.uk/b006qykl.rss',               # In Our Time (BBC)
    'https://feeds.simplecast.com/BqbsxVfO',                         # 99% Invisible
    'https://feeds.simplecast.com/Y8lFbOT4',                         # Freakonomics Radio
    'https://feeds.transistor.fm/acquired',                          # Acquired
    'https://lexfridman.com/feed/podcast/',                          # Lex Fridman Podcast
    'https://cowenconvos.libsyn.com/rss',                            # Conversations with Tyler
    'https://feeds.megaphone.fm/hubermanlab',                        # Huberman Lab
    'https://www.nasa.gov/feeds/podcasts/houston-we-have-a-podcast',  # Houston We Have a Podcast (NASA)
)
DEFAULT_OUT = DEFAULT_PODCASTS
MAX_FEED_BYTES = 40 * 1024 * 1024
EPISODES_PER_SHOW = 50
MIN_MINUTES = 20        # long-form only
MAX_MINUTES = 600       # the longest scene Flicks can be asked for
DESCRIPTION_CHARS = 700
MAX_TAGS = 8
NS = {'itunes': 'http://www.itunes.com/dtds/podcast-1.0.dtd', 'content': 'http://purl.org/rss/1.0/modules/content/'}


class _Text(HTMLParser):
    """Show notes are HTML; keep the text, with a space wherever a tag was."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        self.parts.append(' ')

    def handle_endtag(self, tag):
        self.parts.append(' ')

    def handle_data(self, data):
        self.parts.append(data)


def clean_text(markup):
    parser = _Text()
    parser.feed(markup or '')
    parser.close()
    return ' '.join(''.join(parser.parts).split())


def truncate(text, limit=DESCRIPTION_CHARS):
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(' ', 1)[0].rstrip(' ,;:-')
    return f'{cut}…'


def parse_duration(text):
    """Seconds from itunes:duration ('3017', '50:51', '04:01:20', '3017.5'), or None."""
    text = (text or '').strip()
    if re.fullmatch(r'\d+(\.\d+)?', text):
        return float(text)
    if re.fullmatch(r'\d{1,3}(:\d{1,2}){1,2}', text):
        seconds = 0
        for part in text.split(':'):
            seconds = seconds * 60 + int(part)
        return float(seconds)
    return None


def episode_id(feed_url, key):
    """Stable across imports: the same episode of the same feed always gets the same ID."""
    return 'pod' + hashlib.sha1(f'{feed_url}\n{key}'.encode()).hexdigest()[:12]


def _keywords(text):
    words = (w.strip().lower() for w in (text or '').split(','))
    return list(dict.fromkeys(w for w in words if w and len(w) <= 30))[:MAX_TAGS]


def _image(element):
    """The artwork URL of a channel (itunes:image, else RSS image), or '' when there is none."""
    tag = element.find('itunes:image', NS)
    url = (tag.get('href') if tag is not None else None) or element.findtext('image/url') or ''
    return url.strip() if public_web(url.strip()) else ''


def parse_feed(data, feed_url, per_show=EPISODES_PER_SHOW, min_minutes=MIN_MINUTES):
    """(show, [(catalogue row, episode entry)], skipped reasons) for one RSS feed, newest first."""
    channel = ET.fromstring(data).find('channel')
    if channel is None:
        raise ValueError('not an RSS feed')
    show = clean_text(channel.findtext('title'))
    if not show:
        raise ValueError('the feed has no title')
    genres = list(dict.fromkeys(PODCAST_CATEGORIES[c.get('text')] for c in channel.findall('itunes:category', NS)
                                if c.get('text') in PODCAST_CATEGORIES))
    if not genres:
        raise ValueError('the feed has no Apple Podcasts category')
    moods, intensity = estimate(genres)
    show_link = (channel.findtext('link') or '').strip()
    show_notes = clean_text(channel.findtext('description') or channel.findtext('itunes:summary', namespaces=NS))
    show_tags = _keywords(channel.findtext('itunes:keywords', namespaces=NS))
    show_image = _image(channel)

    found, skipped = [], Counter()
    for item in channel.findall('item'):
        if (item.findtext('itunes:episodeType', namespaces=NS) or '').strip().lower() == 'trailer':
            skipped['trailer'] += 1
            continue
        enclosure = item.find('enclosure')
        audio = (enclosure.get('url') or '').strip() if enclosure is not None else ''
        media_type = (enclosure.get('type') or '').strip().lower() if enclosure is not None else ''
        if not audio or not public_web(audio):
            skipped['no audio file'] += 1
            continue
        if media_type and not media_type.startswith('audio/'):
            skipped['not audio (e.g. a video episode)'] += 1
            continue
        seconds = parse_duration(item.findtext('itunes:duration', namespaces=NS))
        if seconds is None:
            skipped['no duration'] += 1
            continue
        minutes = math.ceil(seconds / 60)
        if minutes < min_minutes:
            skipped[f'shorter than {min_minutes} minutes'] += 1
            continue
        if minutes > MAX_MINUTES:
            skipped[f'longer than {MAX_MINUTES // 60} hours'] += 1
            continue
        try:
            published = parsedate_to_datetime(item.findtext('pubDate') or '')
        except (TypeError, ValueError):
            skipped['no publication date'] += 1
            continue
        title = clean_text(item.findtext('title'))
        if not title:
            skipped['no title'] += 1
            continue
        notes = clean_text(item.findtext('content:encoded', namespaces=NS) or item.findtext('description')
                           or item.findtext('itunes:summary', namespaces=NS)) or show_notes or title
        key = (item.findtext('guid') or '').strip() or audio
        content_id = episode_id(feed_url, key)
        row = {'id': content_id, 'title': title, 'year': published.year, 'kind': 'episode', 'minutes': minutes,
               'genres': genres, 'tags': _keywords(item.findtext('itunes:keywords', namespaces=NS)) or show_tags or genres,
               'moods': moods, 'intensity': intensity, 'description': truncate(notes), 'series': show}
        entry = {'show': show, 'feed': feed_url, 'link': (item.findtext('link') or '').strip() or show_link,
                 'audio': audio, 'type': media_type or 'audio/mpeg', 'published': published.date().isoformat(),
                 'image': show_image}  # one image per show: episode art is often 3000 px and several MB each
        found.append((published.timestamp(), content_id, row, entry))

    found.sort(key=lambda row: (-row[0], row[1]))
    unique = list({content_id: (row, entry) for _, content_id, row, entry in found}.values())
    if len(unique) < len(found):
        skipped['listed twice'] += len(found) - len(unique)
    if len(unique) > per_show:
        skipped[f'older than the newest {per_show}'] += len(unique) - per_show
    kept = unique[:per_show]
    return {'title': show, 'feed': feed_url, 'link': show_link, 'episodes': len(kept)}, kept, skipped


def read_feed_list(path: Path):
    lines = (line.split('#', 1)[0].strip() for line in path.read_text(encoding='utf-8').splitlines())
    return [line for line in lines if line]


def import_podcasts(feeds, out: Path, per_show=EPISODES_PER_SHOW, min_minutes=MIN_MINUTES, fetch=get, log=print):
    """Fetch each feed once and write the catalogue and its episode index. Returns a summary."""
    shows, rows, entries, skipped, failed = [], [], {}, Counter(), {}
    for feed in dict.fromkeys(feeds):
        try:
            if parse.urlsplit(feed).scheme not in WEB_SCHEMES:
                raise ValueError('feeds must be http(s) URLs')
            data = fetch(feed, MAX_FEED_BYTES, accept='application/rss+xml, application/xml, text/xml')
            show, kept, reasons = parse_feed(data, feed, per_show, min_minutes)
        except (OSError, ValueError, ET.ParseError, error.URLError) as exc:
            failed[feed] = str(getattr(exc, 'reason', None) or exc)
            log(f'  failed: {feed} ({failed[feed]})')
            continue
        shows.append(show)
        skipped.update(reasons)
        for row, entry in kept:
            if row['id'] not in entries:
                rows.append(row)
                entries[row['id']] = entry
        log(f"  {show['title']}: {show['episodes']} episodes")
    if not rows:
        raise ValueError('No episodes imported; check the feed URLs')

    out.parent.mkdir(parents=True, exist_ok=True)
    catalogue_tmp, index_tmp = out.with_suffix('.json.tmp'), episodes_path(out).with_suffix('.json.tmp')
    catalogue_tmp.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    index = {'format': FORMAT, 'fetched': datetime.now(timezone.utc).isoformat(timespec='seconds'),
             'shows': shows, 'skipped': dict(skipped), 'failed': failed, 'episodes': entries}
    index_tmp.write_text(json.dumps(index, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    # Never leave files the app would reject: validate both before they replace anything.
    ids = {item.id for item in load_catalog(catalogue_tmp)}
    PodcastIndex.load(index_tmp, ids)
    catalogue_tmp.replace(out)
    index_tmp.replace(episodes_path(out))
    return {'shows': len(shows), 'episodes': len(rows), 'skipped': dict(skipped), 'failed': failed}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build a Flicks podcast catalogue from RSS feeds')
    parser.add_argument('--feed', action='append', default=[], help='An RSS feed URL (repeatable)')
    parser.add_argument('--feeds', type=Path, help='A file of feed URLs, one per line')
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT, help=f'Catalogue to write (default {DEFAULT_OUT})')
    parser.add_argument('--episodes', type=int, default=EPISODES_PER_SHOW, help='Newest episodes to keep per show')
    parser.add_argument('--min-minutes', type=int, default=MIN_MINUTES, help='Skip shorter episodes')
    args = parser.parse_args(argv)
    feeds = [*args.feed, *(read_feed_list(args.feeds) if args.feeds else [])] or list(FEEDS)
    print(f'Reading {len(feeds)} feeds (only the feed URLs are requested). Episodes are downloaded later, '
          'one at a time, when you ask; they are for personal listening and stay out of git.')
    result = import_podcasts(feeds, args.out, args.episodes, args.min_minutes)
    print(f"Wrote {result['episodes']} episodes from {result['shows']} shows to {args.out}")
    for reason, count in sorted(result['skipped'].items()):
        print(f'  skipped {count}: {reason}')
    print(f'Flicks picks it up automatically from {DEFAULT_OUT}; otherwise run: flicks --podcasts {args.out}')


if __name__ == '__main__':
    main()
