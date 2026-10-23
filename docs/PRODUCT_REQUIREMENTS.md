# Product requirements

## Mission and scope

Build a low-cost, AI-native arbitrage intelligence platform that discovers, evaluates, ranks and reports potential resale opportunities. Initial source-to-destination paths are Walmart, Walgreens, Target and other authorized retailers → Amazon. Future paths include Amazon → Walmart and wholesale → Amazon/Walmart. Estimated profit is never guaranteed profit. Inventory purchases always require human judgment and authorization.

## Business defaults

- Inventory budget: $500. Budget checks are per-unit affordability, not a portfolio allocation or purchase recommendation.
- Minimum estimated ROI: 50% of acquisition cost; minimum estimated profit: $5/unit.
- Daily reporting target: top 20 opportunities; prioritize measurable demand and manageable inventory risk.
- Exact identity, package quantity/variation, eligibility, availability, competition, demand, fresh evidence and complete cost inputs are screening prerequisites.
- Missing critical evidence blocks review selection. Mock data is fictional, confidence-capped and never purchase-ready. All supplied-data results also require manual validation.

## V0.2 acceptance criteria

A common retailer connector streams normalized products from user-owned CSV. Authorized APIs, licensed feeds and permitted URL retrieval can implement that interface later; V0.2 performs no remote retrieval. Products carry source, name, URL, normalized GTIN, manufacturer/model, package quantity, variation, purchase price, availability, retrieval time and provenance.

An Amazon provider boundary supplies exact ASIN/GTIN/manufacturer-model matching with explicit ambiguous/missing outcomes, variant and quantity checks, eligibility and matching confidence. The bundled provider is mock-only. No live data or credentials are assumed.

Expanded economics includes referral and FBA fees, inbound shipping, preparation, packaging, storage, sales tax and other transaction costs. Reports expose net profit, ROI, break-even and maximum purchase price, estimation basis and missing evidence. Rank passing rows with explicit profitability, confidence, demand, competition and capital factors.

Six-sheet Excel reports contain executive summary, top 20, all candidates, rejections, data quality and job summary. SQLite final execution history, structured logs, optional SMTP, Docker, CI and legacy CSV behavior remain functional.

## Constraints

Python 3.12, Ubuntu 24.04, Docker, environment-only configuration, no hardcoded credentials. SQLite initially; PostgreSQL only when scale warrants it. Shared production host has approximately 2 GB RAM; cap discovery candidates at 10,000 by default and partition large feeds. Minimal infrastructure, no paid subscriptions or production deployment without approval. Existing hosting is excluded from an incremental <$50/month target; incremental AI target is about $15/month or less. These are targets, not vendor quotes.

## Exclusions

No purchases, unauthorized scraping, CAPTCHA bypass, production credential access, automatic eligibility assertions, live API enablement, paid services, unrelated project access or WeinsteinAgent modifications. No production deployment in this milestone.
