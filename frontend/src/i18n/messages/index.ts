import { en as commonEn, es as commonEs } from './common';
import { en as activityEn, es as activityEs } from './pages/activity';
import { en as automationEn, es as automationEs } from './pages/automation';
import { en as calendarEn, es as calendarEs } from './pages/calendar';
import { en as chatEn, es as chatEs } from './pages/chat';
import { en as memoryEn, es as memoryEs } from './pages/memory';
import { en as overviewEn, es as overviewEs } from './pages/overview';
import { en as permissionsEn, es as permissionsEs } from './pages/permissions';
import { en as runsEn, es as runsEs } from './pages/runs';
import { en as settingsEn, es as settingsEs } from './pages/settings';
import { en as skillsEn, es as skillsEs } from './pages/skills';
import { en as toolsEn, es as toolsEs } from './pages/tools';
import { en as shellEn, es as shellEs } from './shell';

/**
 * Every message the interface can render, grouped by language.
 *
 * Spanish is the reference tree. ``Messages`` and ``MessageKey`` are derived
 * from it, and each English module is annotated with the shape of its Spanish
 * counterpart, so a string that exists in one language and not the other is a
 * compile error rather than a screen with two languages on it.
 */
export const messages = {
  es: {
    common: commonEs,
    shell: shellEs,
    pages: {
      overview: overviewEs,
      chat: chatEs,
      calendar: calendarEs,
      activity: activityEs,
      memory: memoryEs,
      permissions: permissionsEs,
      tools: toolsEs,
      skills: skillsEs,
      runs: runsEs,
      automation: automationEs,
      settings: settingsEs,
    },
  },
  en: {
    common: commonEn,
    shell: shellEn,
    pages: {
      overview: overviewEn,
      chat: chatEn,
      calendar: calendarEn,
      activity: activityEn,
      memory: memoryEn,
      permissions: permissionsEn,
      tools: toolsEn,
      skills: skillsEn,
      runs: runsEn,
      automation: automationEn,
      settings: settingsEn,
    },
  },
};
