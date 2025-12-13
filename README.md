# Grimoire

A self-hosted digital library manager for tabletop RPG content with AI-powered organization, search, and content extraction.

## Features

- **Library Management**: Scan folders for PDFs and build a searchable catalog
- **Cover Extraction**: Automatically extract cover images from PDFs
- **Metadata Extraction**: Extract page count, embedded metadata, and more
- **Manual Tagging**: Organize with game system, product type, and custom tags
- **Collections**: Create custom groupings of products
- **Search**: Full-text search across titles and metadata
- **In-Browser PDF Viewer**: View PDFs directly in the app

## Quick Start

### Prerequisites

- Docker and Docker Compose
- A folder containing your RPG PDFs

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/Live-to-Role/grimoire.git
   cd grimoire
   ```

2. Configure your PDF library path:
   ```bash
   cp .env.example .env
   # Edit .env and set PDF_LIBRARY_PATH to your PDFs folder
   ```

3. Start the services:
   ```bash
   docker-compose up -d
   ```

4. Access the API at http://localhost:8000/api/docs

## Development

### Running in Development Mode

```bash
docker-compose -f docker-compose.dev.yml up
```

This mounts the source code for hot-reloading.

### API Documentation

Once running, visit:
- Swagger UI: http://localhost:8000/api/docs
- ReDoc: http://localhost:8000/api/redoc

### Project Structure

```
grimoire/
├── backend/
│   ├── grimoire/
│   │   ├── api/           # FastAPI routes
│   │   ├── models/        # SQLAlchemy models
│   │   ├── schemas/       # Pydantic schemas
│   │   ├── services/      # Business logic
│   │   └── worker/        # Background tasks
│   ├── requirements.txt
│   └── pyproject.toml
├── frontend/              # React frontend (coming soon)
├── docker/
│   └── Dockerfile.backend
├── docker-compose.yml
└── docs/
    └── grimoire_planning.md
```

## API Endpoints

### Products
- `GET /api/v1/products` - List products with filtering
- `GET /api/v1/products/{id}` - Get product details
- `PATCH /api/v1/products/{id}` - Update product metadata
- `DELETE /api/v1/products/{id}` - Remove product from library
- `GET /api/v1/products/{id}/cover` - Get cover image
- `GET /api/v1/products/{id}/pdf` - View PDF

### Collections
- `GET /api/v1/collections` - List collections
- `POST /api/v1/collections` - Create collection
- `GET /api/v1/collections/{id}` - Get collection with products
- `PATCH /api/v1/collections/{id}` - Update collection
- `DELETE /api/v1/collections/{id}` - Delete collection

### Tags
- `GET /api/v1/tags` - List tags
- `POST /api/v1/tags` - Create tag
- `PATCH /api/v1/tags/{id}` - Update tag
- `DELETE /api/v1/tags/{id}` - Delete tag

### Folders
- `GET /api/v1/folders` - List watched folders
- `POST /api/v1/folders` - Add watched folder
- `POST /api/v1/folders/scan` - Trigger library scan
- `GET /api/v1/folders/library/stats` - Get library statistics

### Search
- `GET /api/v1/search?q=query` - Search products

## License

GPL-3.0

## Contributing

See [CONTRIBUTING.md](docs/contributing.md) for guidelines.
