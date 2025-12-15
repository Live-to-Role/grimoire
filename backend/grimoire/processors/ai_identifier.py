"""
AI-powered product identification.
Uses LLMs to identify game system, publisher, product type, etc. from PDF content.
"""

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

from grimoire.config import settings


# Approximate pricing per 1M tokens (as of late 2024)
MODEL_PRICING = {
    # OpenAI
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    # Anthropic
    "claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
    "claude-3-sonnet-20240229": {"input": 3.00, "output": 15.00},
    "claude-3-opus-20240229": {"input": 15.00, "output": 75.00},
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    # Ollama (free/local)
    "llama3.2": {"input": 0.0, "output": 0.0},
    "llama3.1": {"input": 0.0, "output": 0.0},
    "mistral": {"input": 0.0, "output": 0.0},
}

# Default models per provider
DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-haiku-20240307",
    "ollama": "llama3.2",
}


@dataclass
class CostEstimate:
    """Estimated cost for an AI operation."""
    provider: str
    model: str
    input_tokens: int
    estimated_output_tokens: int
    input_cost: float
    output_cost: float
    total_cost: float
    is_free: bool


def estimate_tokens(text: str) -> int:
    """Estimate token count for text. Rough approximation: ~4 chars per token."""
    return len(text) // 4


def estimate_cost(
    text: str,
    provider: str | None = None,
    model: str | None = None,
    task_type: str = "identify",
) -> CostEstimate:
    """
    Estimate the cost of an AI operation.
    
    Args:
        text: The text to process
        provider: AI provider (openai, anthropic, ollama)
        model: Specific model to use
        task_type: Type of task (identify, suggest_tags)
    
    Returns:
        CostEstimate with pricing breakdown
    """
    # Determine provider
    if provider is None:
        if os.getenv("OPENAI_API_KEY"):
            provider = "openai"
        elif os.getenv("ANTHROPIC_API_KEY"):
            provider = "anthropic"
        else:
            provider = "ollama"
    
    # Determine model
    if model is None:
        model = DEFAULT_MODELS.get(provider, "gpt-4o-mini")
    
    # Get pricing
    pricing = MODEL_PRICING.get(model, {"input": 0.0, "output": 0.0})
    
    # Estimate tokens
    # Include prompt template overhead (~200 tokens)
    prompt_overhead = 200
    input_tokens = estimate_tokens(text[:4000]) + prompt_overhead
    
    # Estimate output tokens based on task
    if task_type == "identify":
        estimated_output = 150  # JSON response ~150 tokens
    elif task_type == "suggest_tags":
        estimated_output = 200  # Tag suggestions ~200 tokens
    else:
        estimated_output = 200
    
    # Calculate costs (pricing is per 1M tokens)
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (estimated_output / 1_000_000) * pricing["output"]
    total_cost = input_cost + output_cost
    
    return CostEstimate(
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        estimated_output_tokens=estimated_output,
        input_cost=input_cost,
        output_cost=output_cost,
        total_cost=total_cost,
        is_free=total_cost == 0,
    )


def estimate_batch_cost(
    texts: list[str],
    provider: str | None = None,
    model: str | None = None,
    task_type: str = "identify",
) -> dict[str, Any]:
    """
    Estimate cost for processing multiple items.
    
    Returns:
        Dictionary with total cost and per-item breakdown
    """
    estimates = [estimate_cost(text, provider, model, task_type) for text in texts]
    
    total_input_tokens = sum(e.input_tokens for e in estimates)
    total_output_tokens = sum(e.estimated_output_tokens for e in estimates)
    total_cost = sum(e.total_cost for e in estimates)
    
    return {
        "provider": estimates[0].provider if estimates else provider,
        "model": estimates[0].model if estimates else model,
        "item_count": len(texts),
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_cost_usd": round(total_cost, 6),
        "is_free": total_cost == 0,
        "cost_per_item_usd": round(total_cost / len(texts), 6) if texts else 0,
    }


IDENTIFICATION_PROMPT = """Analyze this RPG PDF text and return a JSON object with these fields:
- game_system: e.g. "Dungeons & Dragons 5th Edition", "Pathfinder 2nd Edition", "Dungeon Crawl Classics", "Old-School Essentials", or null
- genre: one of "Fantasy", "Horror", "Science Fiction", "Modern", "Historical", or null
- product_type: e.g. "Adventure", "Supplement", "Core Rulebook", "Bestiary", "Setting", "Zine", or null  
- publisher: publisher name or null
- author: primary author/writer name(s) or null
- title: product title or null
- publication_year: year as number or null
- level_range_min: minimum character level or null
- level_range_max: maximum character level or null
- description: 1-2 sentence description or null
- confidence: "high", "medium", or "low"

Text to analyze:
{text}

Return ONLY the JSON object, nothing else."""


TAG_SUGGESTION_PROMPT = """Analyze this RPG PDF text and suggest relevant tags.

Return a JSON object with:
- themes: array of theme tags (e.g. "horror", "wilderness", "urban", "dungeon", "mystery", "political")
- content_types: array of content type tags (e.g. "monsters", "maps", "random-tables", "npcs", "magic-items", "puzzles")
- settings: array of setting tags (e.g. "fantasy", "sci-fi", "post-apocalyptic", "historical")
- tone: array of tone tags (e.g. "grimdark", "comedic", "heroic", "sandbox")
- confidence: "high", "medium", or "low"

Only include tags that are clearly present in the content. Limit to 3-5 tags per category.

Text to analyze:
{text}

Return ONLY the JSON object, nothing else."""


async def identify_with_openai(text: str, api_key: str) -> dict[str, Any]:
    """Use OpenAI API for identification."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "user", "content": IDENTIFICATION_PROMPT.format(text=text)}
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)


async def identify_with_anthropic(text: str, api_key: str) -> dict[str, Any]:
    """Use Anthropic API for identification."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "claude-3-haiku-20240307",
                "max_tokens": 1024,
                "messages": [
                    {"role": "user", "content": IDENTIFICATION_PROMPT.format(text=text)}
                ],
            },
        )
        response.raise_for_status()
        data = response.json()
        content = data["content"][0]["text"].strip()
        
        # Handle JSON that may have newlines inside strings
        # Find the outermost JSON object
        start_idx = content.find('{')
        end_idx = content.rfind('}')
        
        if start_idx != -1 and end_idx != -1:
            json_str = content[start_idx:end_idx + 1]
            return json.loads(json_str)
        
        return json.loads(content)


async def identify_with_ollama(text: str, base_url: str, model: str = "llama3.2") -> dict[str, Any]:
    """Use Ollama for local identification."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{base_url}/api/generate",
            json={
                "model": model,
                "prompt": IDENTIFICATION_PROMPT.format(text=text),
                "stream": False,
                "format": "json",
            },
        )
        response.raise_for_status()
        data = response.json()
        content = data["response"]
        return json.loads(content)


async def identify_product(
    text: str,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """
    Identify product metadata using AI.
    
    Args:
        text: Extracted text from the PDF
        provider: AI provider to use ("openai", "anthropic", "ollama", or None for auto)
        model: Specific model to use (optional)
    
    Returns:
        Dictionary with identified metadata
    """
    truncated_text = text[:4000]
    
    openai_key = os.getenv("OPENAI_API_KEY", "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    
    if provider is None:
        if openai_key:
            provider = "openai"
        elif anthropic_key:
            provider = "anthropic"
        elif ollama_url:
            provider = "ollama"
        else:
            return {"error": "No AI provider configured"}
    
    try:
        if provider == "openai":
            if not openai_key:
                return {"error": "OpenAI API key not configured"}
            result = await identify_with_openai(truncated_text, openai_key)
        elif provider == "anthropic":
            if not anthropic_key:
                return {"error": "Anthropic API key not configured"}
            result = await identify_with_anthropic(truncated_text, anthropic_key)
        elif provider == "ollama":
            result = await identify_with_ollama(
                truncated_text, 
                ollama_url, 
                model or "llama3.2"
            )
        else:
            return {"error": f"Unknown provider: {provider}"}
        
        result["provider"] = provider
        return result
        
    except httpx.HTTPStatusError as e:
        return {"error": f"API error: {e.response.status_code} - {e.response.text}"}
    except json.JSONDecodeError as e:
        return {"error": f"Failed to parse AI response as JSON: {str(e)[:100]}"}
    except Exception as e:
        return {"error": f"Identification failed: {str(e)}"}


def get_available_providers() -> dict[str, bool]:
    """Check which AI providers are available."""
    return {
        "openai": bool(os.getenv("OPENAI_API_KEY")),
        "anthropic": bool(os.getenv("ANTHROPIC_API_KEY")),
        "ollama": bool(os.getenv("OLLAMA_BASE_URL")),
    }


async def suggest_tags_with_openai(text: str, api_key: str) -> dict[str, Any]:
    """Use OpenAI API for tag suggestions."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "user", "content": TAG_SUGGESTION_PROMPT.format(text=text)}
                ],
                "temperature": 0.3,
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)


async def suggest_tags_with_anthropic(text: str, api_key: str) -> dict[str, Any]:
    """Use Anthropic API for tag suggestions."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "claude-3-haiku-20240307",
                "max_tokens": 1024,
                "messages": [
                    {"role": "user", "content": TAG_SUGGESTION_PROMPT.format(text=text)}
                ],
            },
        )
        response.raise_for_status()
        data = response.json()
        content = data["content"][0]["text"].strip()
        
        start_idx = content.find('{')
        end_idx = content.rfind('}')
        
        if start_idx != -1 and end_idx != -1:
            json_str = content[start_idx:end_idx + 1]
            return json.loads(json_str)
        
        return json.loads(content)


async def suggest_tags_with_ollama(text: str, base_url: str, model: str = "llama3.2") -> dict[str, Any]:
    """Use Ollama for local tag suggestions."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{base_url}/api/generate",
            json={
                "model": model,
                "prompt": TAG_SUGGESTION_PROMPT.format(text=text),
                "stream": False,
                "format": "json",
            },
        )
        response.raise_for_status()
        data = response.json()
        content = data["response"]
        return json.loads(content)


async def suggest_tags(
    text: str,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """
    Suggest tags for a product using AI.
    
    Args:
        text: Extracted text from the PDF
        provider: AI provider to use ("openai", "anthropic", "ollama", or None for auto)
        model: Specific model to use (optional)
    
    Returns:
        Dictionary with suggested tags by category
    """
    truncated_text = text[:4000]
    
    openai_key = os.getenv("OPENAI_API_KEY", "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    
    if provider is None:
        if openai_key:
            provider = "openai"
        elif anthropic_key:
            provider = "anthropic"
        elif ollama_url:
            provider = "ollama"
        else:
            return {"error": "No AI provider configured"}
    
    try:
        if provider == "openai":
            if not openai_key:
                return {"error": "OpenAI API key not configured"}
            result = await suggest_tags_with_openai(truncated_text, openai_key)
        elif provider == "anthropic":
            if not anthropic_key:
                return {"error": "Anthropic API key not configured"}
            result = await suggest_tags_with_anthropic(truncated_text, anthropic_key)
        elif provider == "ollama":
            result = await suggest_tags_with_ollama(
                truncated_text, 
                ollama_url, 
                model or "llama3.2"
            )
        else:
            return {"error": f"Unknown provider: {provider}"}
        
        result["provider"] = provider
        return result
        
    except httpx.HTTPStatusError as e:
        return {"error": f"API error: {e.response.status_code} - {e.response.text}"}
    except json.JSONDecodeError as e:
        return {"error": f"Failed to parse AI response as JSON: {str(e)[:100]}"}
    except Exception as e:
        return {"error": f"Tag suggestion failed: {str(e)}"}


def flatten_suggested_tags(suggestions: dict[str, Any]) -> list[str]:
    """Flatten tag suggestions into a single list of tag names."""
    tags = []
    for category in ["themes", "content_types", "settings", "tone"]:
        if category in suggestions and isinstance(suggestions[category], list):
            tags.extend(suggestions[category])
    return tags
