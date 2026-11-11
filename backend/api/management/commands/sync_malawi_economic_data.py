import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


INDICATORS = (
    ('FP.CPI.TOTL.ZG', 'Inflation, consumer prices (annual %)', '%'),
    ('NY.GDP.MKTP.KD.ZG', 'GDP growth (annual %)', '%'),
    ('PA.NUS.FCRF', 'Official exchange rate (MWK per US$)', 'MWK per US$'),
    ('FR.INR.RINR', 'Real interest rate', '%'),
    ('FS.AST.PRVT.GD.ZS', 'Domestic credit to private sector (% of GDP)', '% of GDP'),
)
WORLD_BANK_API_URL = 'https://api.worldbank.org/v2/country/MWI/indicator/{code}'


class Command(BaseCommand):
    help = 'Download Malawi economic indicators from the World Bank Indicators API.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--years',
            type=int,
            default=10,
            help='Number of non-empty annual observations to store per indicator.',
        )

    def handle(self, *args, **options):
        years = options['years']
        if years < 1 or years > 30:
            raise CommandError('--years must be between 1 and 30.')

        indicators = []
        for code, name, unit in INDICATORS:
            observations = self._fetch_indicator(code, years)
            indicators.append({
                'code': code,
                'name': name,
                'unit': unit,
                'observations': observations,
            })
            self.stdout.write(f'Fetched {len(observations)} observations for {code}.')

        dataset = {
            'country': 'Malawi',
            'country_code': 'MWI',
            'source': 'World Bank Indicators API',
            'source_url': 'https://api.worldbank.org/v2/country/MWI/indicator',
            'updated_at': datetime.now(timezone.utc).isoformat(),
            'indicators': indicators,
        }
        dataset_path = Path(settings.ECONOMIC_DATASET_PATH)
        dataset_path.parent.mkdir(parents=True, exist_ok=True)
        dataset_path.write_text(
            json.dumps(dataset, indent=2, ensure_ascii=False) + '\n',
            encoding='utf-8',
        )
        self.stdout.write(self.style.SUCCESS(f'Wrote dataset to {dataset_path}.'))

    def _fetch_indicator(self, code, years):
        query = urlencode({'format': 'json', 'per_page': 100})
        url = f'{WORLD_BANK_API_URL.format(code=code)}?{query}'
        try:
            with urlopen(url, timeout=30) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except (OSError, ValueError) as error:
            raise CommandError(f'Could not download {code}: {error}') from error

        records = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
        if not isinstance(records, list):
            raise CommandError(f'World Bank returned an invalid response for {code}.')

        observations = [
            {'year': record.get('date'), 'value': record.get('value')}
            for record in records
            if isinstance(record, dict) and record.get('value') is not None
        ]
        return observations[:years]
