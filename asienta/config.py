"""Settings: one INI file (config.ini), optionally layered on top of a preset.

    presets/<name>.ini  ->  config.ini  ->  environment variables (secrets)

Secrets never need to live in the file: GEMINI_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY, ASIENTA_TOKEN,
ASIENTA_SAGE50_PASSWORD, ASIENTA_MAILBOX_PASSWORD and HOLDED_API_KEY override it.
"""
import configparser
import os
import re
from dataclasses import dataclass

PACKAGE = os.path.dirname(os.path.abspath(__file__))
PRESETS = os.path.join(PACKAGE, 'presets')


@dataclass
class Category:
    name: str
    account: str
    description: str


def parse_pairs(text):
    """'21:472000021, 10:472000010' -> {21.0: '472000021', 10.0: '472000010'}."""
    out = {}
    for pair in (text or '').split(','):
        if ':' in pair:
            k, v = pair.split(':', 1)
            try:
                out[float(k.strip().replace(',', '.'))] = v.strip()
            except ValueError:
                pass
    return out


def parse_list(text):
    return [x.strip() for x in (text or '').split(',') if x.strip()]


class Settings:
    def __init__(self, path=None, overrides=None):
        self.path = path
        self.base = os.path.dirname(os.path.abspath(path)) if path else os.getcwd()
        cfg = configparser.ConfigParser(inline_comment_prefixes=(';', '#'), interpolation=None)
        cfg.optionxform = str                                  # keep category names as written
        files = []
        if path:
            probe = configparser.ConfigParser(inline_comment_prefixes=(';', '#'), interpolation=None)
            probe.read(path, encoding='utf-8')
            preset = probe.get('app', 'preset', fallback='').strip()
            if preset:
                p = preset if os.path.isfile(preset) else os.path.join(PRESETS, f'{preset}.ini')
                if not os.path.isfile(p):
                    raise SystemExit(f'Preset not found: {preset}')
                files.append(p)
            files.append(path)
        cfg.read(files, encoding='utf-8')
        for section, values in (overrides or {}).items():
            if not cfg.has_section(section):
                cfg.add_section(section)
            for k, v in values.items():
                cfg.set(section, k, str(v))
        self.cfg = cfg

    # ------------------------------------------------------------------ typed access
    def get(self, section, key, default=''):
        v = self.cfg.get(section, key, fallback=None)
        return default if v is None or v.strip() == '' else v.strip()

    def int(self, section, key, default=0):
        try:
            return int(self.get(section, key, default))
        except ValueError:
            return default

    def float(self, section, key, default=0.0):
        try:
            return float(self.get(section, key, default))
        except ValueError:
            return default

    def bool(self, section, key, default=False):
        v = self.get(section, key, '')
        return default if not v else v.lower() in ('1', 'true', 'yes', 'on', 'si', 'sí')

    def section(self, name):
        return dict(self.cfg[name]) if self.cfg.has_section(name) else {}

    def path_(self, section, key, default=''):
        """A path from the config, relative to the config file."""
        v = self.get(section, key, default)
        return os.path.normpath(os.path.join(self.base, os.path.expanduser(v))) if v else ''

    # ------------------------------------------------------------------ derived
    @property
    def language(self):
        lang = self.get('app', 'language', 'es').lower()
        return lang if lang in ('es', 'en') else 'es'

    @property
    def data_dir(self):
        return self.path_('app', 'data', 'data')

    @property
    def token(self):
        return os.environ.get('ASIENTA_TOKEN') or self.get('app', 'access_token')

    def secret(self, section, key, env):
        return (os.environ.get(env) or self.get(section, key)).strip().strip('"\'').strip()

    def categories(self):
        """Line categories the AI assigns, each with the expense account it goes to.
        [categories]  drinks = 600000200 | wine, beer, soft drinks, water, coffee"""
        out = []
        for name, value in self.section('categories').items():
            account, _, desc = value.partition('|')
            account = re.sub(r'\D', '', account)
            if name.strip():
                out.append(Category(name.strip().lower(), account, desc.strip()))
        return out

    def brand(self):
        accent = self.get('brand', 'accent', '#4F46E5')
        if not re.fullmatch(r'#[0-9A-Fa-f]{6}', accent):
            accent = '#4F46E5'
        return {'name': self.get('brand', 'name', 'Asienta'),
                'tagline': self.get('brand', 'tagline', ''),
                'accent': accent,
                'has_logo': bool(self.logo_path())}

    def logo_path(self):
        p = self.path_('brand', 'logo')
        return p if p and os.path.isfile(p) else ''
