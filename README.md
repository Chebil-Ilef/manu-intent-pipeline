# Manufacturing Intent Intelligence System

> A production-ready n8n workflow for identifying and analyzing intent signals from manufacturing companies through automated web scraping, news monitoring, and financial data aggregation.

## Architecture

### Core Components

1. **n8n Workflow Engine** - Orchestrates the entire data pipeline
2. **Scrapy Web Scraper** - Extracts manufacturing industry news and updates
3. **FastAPI Data Processing Service** - Handles content filtering and enrichment
4. **SQLite State Management** - Prevents duplicate processing
5. **Financial Data Integration** - Enriches company profiles with stock data

### Data Flow

```
Manufacturing News Sources → Scrapy Spider → Content Processing → 
Intent Analysis → Company Profiling → Financial Enrichment → 
Structured Output → n8n Workflow Actions
```

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Environment variables file (`.env`)

### 1. Clone and Setup

```bash
git clone <repository-url>
cd manu-intent-pipeline
```

### 2. Configure Environment

Create `.env` file following `.env.example`

### 3. Launch System

```bash
docker-compose up --build -d
```

### 4. Access Interfaces

- **n8n Workflow Editor**: http://localhost:5678
- **Data Processing API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs

## API Endpoints

### `/scrape` - Content Collection
Triggers manufacturing news scraping with date filtering:
```bash
curl "http://localhost:8000/scrape?cutoff=2025-01-01"
```

### `/profanity` - Content Filtering
Filters and cleans scraped content:
```bash
curl -X POST "http://localhost:8000/profanity" \
  -H "Content-Type: application/json" \
  -d '{"text": "content to filter", "url": "source_url"}'
```

### `/stocks` - Financial Enrichment
Retrieves real-time financial data for target companies:
```bash
curl "http://localhost:8000/stocks"
```

## Intent Signal Detection

The system identifies buying intent through:

- **News Mentions** - Product launches, partnerships, expansions
- **Website Updates** - New hiring, technology adoption
- **Financial Indicators** - Stock performance, investment rounds
- **Content Analysis** - Language patterns indicating purchasing behavior
- **Competitive Intelligence** - Market positioning changes

## Development

### Local Development
```bash
# Start individual services
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Run scrapy directly
cd themanufacturer
scrapy crawl tm_sections -a cutoff=2025-01-01
```

### Testing
```bash
# Test API endpoints
python -m pytest tests/

# Validate scrapy spider
cd themanufacturer
scrapy check tm_sections
```
