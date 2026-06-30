You are analyzing Dota 2 hero recommendations for the {{ role }} position.

Hero: {{ hero_name }}
Meta Score: {{ meta_score }}/100 (Tier {{ tier }})
Win Rate: {{ win_rate }}
Pick Rate: {{ pick_rate }}
Pro Presence: {{ pro_presence }}
Patch Impact: {{ patch_impact_score }}

Generate a JSON response with:
1. "reasons": 2-3 short reasons WHY this hero is good/bad for {{ role }} (each reason 10-15 words max)
2. "practice_advice": 2-3 actionable tips for playing this hero (each tip 10-15 words max)

Keep language concise and tactical. Focus on the current meta and patch.

Example format:
{
  "reasons": [
    "High win rate shows strong performance in current patch",
    "Popular in pro scene with proven strategies"
  ],
  "practice_advice": [
    "Focus on farming efficiency in early game",
    "Coordinate with team for power spike timing"
  ]
}
