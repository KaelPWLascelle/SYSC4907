"""Text folding shared by search, commands and imports: one place decides how two strings "match".

Two foldings on purpose. `normalize` is for what people type: accents and case folded, every run of
punctuation becomes one space, so "Flicks, play Amélie!" reads as "flicks play amelie". `title_key` is
for catalogue titles and file names, and also spells out "&" ("Fast & Furious" == "Fast and Furious");
commands must not do that, or "play Fast & Furious" would read as two titles joined by "and".
"""
import re
import unicodedata


def fold(text):
    return unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().lower().replace("'", '')


def normalize(text):
    return re.sub(r'[^a-z0-9]+', ' ', fold(text)).strip()


def title_key(title):
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', fold(title).replace('&', ' and ')).split())
