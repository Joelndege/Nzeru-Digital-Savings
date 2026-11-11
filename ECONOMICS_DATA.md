# Malawi Economics Knowledge Base

The assistant uses a local, dated Malawi economic dataset instead of treating old model knowledge as current fact. The dataset is sourced from the World Bank Indicators API and contains annual inflation, GDP growth, exchange-rate, real-interest-rate, and private-sector-credit observations.

## Refresh the dataset

From the repository root, run:

```powershell
python backend/manage.py sync_malawi_economic_data --years 10
```

Schedule this command monthly or after official indicator releases. The World Bank API data is annual and should not be described as a real-time market price.

## How the assistant uses it

For Malawi economic questions, the API loads the latest observation for each indicator and sends the dated snapshot to the configured AI provider. The assistant is instructed to name the source and observation year. The economic facts are retrieved at response time; this is safer than fine-tuning them into the language model, where they would become stale.

Set `CLOUDFLARE_ACCOUNT_ID` and `AI_API_KEY` in the backend environment to use Cloudflare Workers AI. The default model is Meta Llama 3.2 3B. Without a key, the app returns a short dataset-based fallback. The Cloudflare Free plan includes a daily Workers AI allowance; after it is used, requests can fail until the allowance resets.
