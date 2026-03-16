import { readFile } from 'fs/promises';
import { homedir } from 'os';
import { join } from 'path';

// Claude Code has no model cache file — hardcode the known aliases.
// These alias names are stable; the full model IDs behind them update automatically.
const CLAUDE_MODELS = [
  { id: 'sonnet', label: 'Sonnet 4.6' },
  { id: 'opus',   label: 'Opus 4.6'   },
  { id: 'haiku',  label: 'Haiku 4.5'  },
];

/**
 * Returns { models, effortLevels } for a given tool.
 * - models: [{ id, label, defaultEffort?, effortLevels? }]
 * - effortLevels: string[] | null (null means tool uses a binary thinking toggle)
 */
export async function getModelsForTool(toolId) {
  if (toolId === 'claude') {
    return { models: CLAUDE_MODELS, effortLevels: null };
  }
  if (toolId === 'codex') {
    return getCodexModels();
  }
  return { models: [], effortLevels: null };
}

async function getCodexModels() {
  try {
    const raw = await readFile(join(homedir(), '.codex', 'models_cache.json'), 'utf-8');
    const data = JSON.parse(raw);
    const models = (data.models || [])
      .filter(m => m.visibility === 'list')
      .map(m => ({
        id: m.slug,
        label: m.display_name,
        defaultEffort: m.default_reasoning_level || 'medium',
        effortLevels: (m.supported_reasoning_levels || []).map(r => r.effort),
      }));
    // Union of all effort levels across all visible models
    const effortLevels = [...new Set(models.flatMap(m => m.effortLevels))];
    return { models, effortLevels };
  } catch {
    return { models: [], effortLevels: ['low', 'medium', 'high', 'xhigh'] };
  }
}
