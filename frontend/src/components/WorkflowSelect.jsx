import React from 'react';
import {USER_SKILL, skillsFor} from '../client';

// The Workflow menu: Automatic, the profile's built-in skills, the user's own skills, then
// skills another account shared with one of the user's groups. User skills assigned to
// other profiles are left out.
function WorkflowSelect({profile, userSkills, value, onChange, disabled}) {
  const info = id => profile?.skill_info?.find(s => s.id === id);
  const builtIn = profile?.skills || [];
  const offered = skillsFor(profile, userSkills);
  const own = offered.filter(s => !s.shared), shared = offered.filter(s => s.shared);
  return (
    <select value={value} disabled={disabled} onChange={e => onChange(e.target.value)}>
      <option value="">Automatic{profile?.default_skill ? ` · ${info(profile.default_skill)?.title || profile.default_skill}` : ''}</option>
      {builtIn.length > 0 && (
        <optgroup label="Built-in">
          {builtIn.map(s => <option key={s} value={s}>{info(s)?.title || s}</option>)}
        </optgroup>
      )}
      {own.length > 0 && (
        <optgroup label="My skills">
          {own.map(s => <option key={s.id} value={USER_SKILL + s.id}>{s.name}</option>)}
        </optgroup>
      )}
      {shared.length > 0 && (
        <optgroup label="Shared with me">
          {shared.map(s => <option key={s.id} value={USER_SKILL + s.id}>{s.name} · {s.shared_by}</option>)}
        </optgroup>
      )}
    </select>
  );
}

export default WorkflowSelect;
