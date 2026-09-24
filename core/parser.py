import httpx
import re
from typing import List, Dict, Any

class LLMPartsParser:
    @staticmethod
    async def fetch_content(url: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.text
        except Exception as e:
            print(f"Error fetching url: {e}")
            return ""

    @staticmethod
    def parse_agents(content: str) -> List[Dict[str, Any]]:
        agents = []
        # Matches ## [Title](URL)
        pattern = r"##\s*\[([^\]]+)\]\s*\(([^)]+)\)"
        matches = re.findall(pattern, content)
        for title, url in matches:
            agents.append({
                "title": title,
                "source_url": url,
                "description": f"Agent discovered from {url}",
                "tags": [],
                "status": "active"
            })
        return agents
