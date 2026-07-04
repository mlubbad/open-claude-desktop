// Loads the available Agent Skills once, for the composer's slash-command autocomplete.

import { useEffect, useState } from "react";

import { type SkillSummary, skills as skillsApi } from "../api/client";

export function useSkills(): SkillSummary[] {
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  useEffect(() => {
    skillsApi
      .list()
      .then(setSkills)
      .catch(() => setSkills([]));
  }, []);
  return skills;
}
