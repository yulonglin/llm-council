# Specification: Morning Wake System

## Overview
**Created**: 2026-01-14
**Status**: Draft

A personal system combining medication timing protocol, accountability mechanisms, and tracking to help consistently get out of bed by 10:30am and start work by 11am, 5/7 weekdays.

## Context & Motivation

**Current state:**
- 10am alarm → out of bed ~12:30pm or later → office 2-4pm → start work
- 2.5+ hours lost daily between alarm and getting up
- Pattern: dismiss alarm and sleep more, OR stay awake but scroll/procrastinate in bed
- "I'm groggy, should sleep more" rationalization kicks in (mixed validity)

**What works:**
- Meetings force getting up (groggy but functional)
- External structure (uni: set meal times, deadlines, lectures)

**What failed:**
- Multiple alarm systems (Watch + AutoSleep) - dismissed or ignored
- Focusmate - worked briefly, then canceled/postponed sessions
- Beeminder - gamed it, felt unfair to pay penalties for "valid" reasons
- Boss-as-a-service - similar degradation

**Contributing factors:**
- Mirtazapine (bedtime sedative) timing is variable - sometimes delayed to stay alert for evening work
- This variability likely causes inconsistent morning grogginess
- SSRIs may have reduced activation energy alongside anxiety
- General malaise, not specific dread - enjoys work once started
- Cold outside bed as physical barrier

**Key insight:** The alarm isn't the problem - conscious decision to stay in bed is. Accountability systems fail when opt-out is easy.

## Requirements

### Functional Requirements

**Evening Protocol:**
- **[REQ-001]** System MUST remind user to take mirtazapine at 10:00pm
- **[REQ-002]** System MUST track whether meds were taken and at what time
- **[REQ-003]** System SHOULD encourage consistent bedtime (target: midnight) via gentle nudges, not hard rules

**Morning Protocol:**
- **[REQ-004]** System MUST provide wake alarm at 10:00am
- **[REQ-005]** System MUST require a check-in action by 10:30am that confirms user is out of bed
- **[REQ-006]** System SHOULD make check-in hard to complete from bed (e.g., QR code in bathroom, or question requiring standing)
- **[REQ-007]** If check-in not completed by 10:30am, system MUST escalate (see escalation tiers below)

**Tracking:**
- **[REQ-008]** System MUST automatically track sleep data via Apple Watch
- **[REQ-009]** System MUST track: meds time, bed-exit time, work-start time (via simple taps, not manual entry)
- **[REQ-010]** System SHOULD surface weekly trends to identify patterns

**Portability:**
- **[REQ-011]** System MUST work without smart home devices (user testing nomadic lifestyle)
- **[REQ-012]** System MUST work with just phone + Apple Watch

### Non-Functional Requirements
- **Sustainability**: System MUST handle bad days gracefully - no shame spirals
- **Budget**: Solution SHOULD cost ≤$30/month
- **Automation**: Tracking SHOULD be as automated as possible (minimal manual logging)

## Design

### High-Level Architecture

```
EVENING (10pm)                    MORNING (10am)                    ESCALATION
    │                                 │                                 │
    ▼                                 ▼                                 ▼
┌─────────────┐               ┌─────────────┐               ┌─────────────────┐
│ Meds Remind │               │ Wake Alarm  │               │ 10:35 - Reminder│
│ (10:00pm)   │               │ (Watch+App) │               │ 10:45 - Partner │
└─────────────┘               └─────────────┘               │ 11:00 - RM ping │
       │                             │                       └─────────────────┘
       ▼                             ▼                                 │
┌─────────────┐               ┌─────────────┐                         ▼
│ Log meds    │               │ Check-in    │               ┌─────────────────┐
│ time (tap)  │               │ by 10:30am  │               │ Log as failed   │
└─────────────┘               └─────────────┘               │ (no punishment) │
                                     │                       └─────────────────┘
                                     ▼
                              ┌─────────────┐
                              │ Start work  │
                              │ by 11:00am  │
                              └─────────────┘
```

### Escalation Tiers

| Time | Action | Rationale |
|------|--------|-----------|
| 10:30am | Aggressive alarm / app notification | First prompt |
| 10:35am | Second reminder + "you're running late" | Gentle nudge |
| 10:45am | Text to partner (auto or manual) | Social accountability |
| 11:00am | Ping research manager or skip | Higher stakes |
| 11:15am | Log as failed day, no further action | Prevent harassment |

**Failure handling:** No punishment beyond logging. Weekly review surfaces patterns. Goal is data, not shame.

### Check-in Mechanism Options

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **QR code in bathroom** | Forces physical movement | Need to print, not portable | Maybe |
| **Photo of something outside bedroom** | Verifiable, portable | Can cheat with old photo | Maybe |
| **Shake phone 50 times** | Can't do from bed | Annoying, can cheat | No |
| **NFC tag on coffee maker** | Forces movement to kitchen | Not portable | No |
| **Simple "I'm up" message** | Easy, low friction | Too easy to lie from bed | Baseline |
| **Time-limited math problem** | Requires alertness | Can still do from bed | No |

**Recommendation:** Start with "I'm up" message to partner/bot as baseline. Add QR code or photo verification if gaming becomes an issue.

### Candidate Apps/Tools

| Tool | Purpose | Cost | Notes |
|------|---------|------|-------|
| **Alarmy** | Alarm with QR/photo requirement | Free/$5/mo | Popular, proven |
| **Focusmate** | Morning accountability call | $10/mo | Previously degraded, but could retry |
| **iOS Shortcuts** | Automate logging, reminders | Free | Native, but requires setup |
| **Streaks** | Habit tracking | $5 one-time | Good for meds timing |
| **Beeminder** | Financial stakes | Variable | Previously gamed, use cautiously |
| **Custom bot** | Telegram/Discord check-in | Free | Would need to build |

### Evening Protocol Detail

```
9:30pm  - Soft reminder: "Wind down, meds in 30 min"
10:00pm - Hard reminder: "Take mirtazapine now"
10:15pm - If not confirmed: "Meds taken yet?"
11:00pm - Soft reminder: "Consider wrapping up work"
12:00am - "Bedtime - screens away ideally"
```

User agreed to prioritize mornings over evening work flexibility. The 10pm meds rule is the highest-leverage intervention.

## Edge Cases & Error Handling

| Scenario | Handling |
|----------|----------|
| Bad day (sleep until 1pm) | Log it, no punishment, try again tomorrow |
| Legitimate reason (sick, travel) | Pause system for the day, log reason |
| Partner unavailable for escalation | Skip to next tier or log as "no escalation available" |
| Multiple failed days in a row | Weekly review surfaces this; consider discussing with therapist/RM |
| Meds reminder dismissed repeatedly | Track pattern, discuss with prescriber if chronic |
| Hostel/travel environment | System must work with phone+watch only |

## Acceptance Criteria

- [ ] **AC-1**: After 2 weeks, mirtazapine taken within 30min of 10pm on ≥5/7 days
- [ ] **AC-2**: After 4 weeks, out of bed by 10:30am on ≥3/7 weekdays (improvement from ~0)
- [ ] **AC-3**: After 4 weeks, work started by 11am on ≥3/7 weekdays
- [ ] **AC-4**: System remains in use (not disabled/abandoned) for full 30 days
- [ ] **AC-5**: User can articulate what patterns emerged from tracking data

## Out of Scope

- Smart home automation (lights, thermostat) - not portable
- Major medication changes - discuss with prescriber separately
- Solving underlying motivation/malaise - this is a behavioral intervention, not therapy
- Perfect consistency - goal is improvement, not 100%
- Weekend wake times - focus on weekdays for now

## Open Questions

- [ ] Should check-in go to partner, research manager, both, or just an app?
- [ ] What happens if user is genuinely sick but system escalates anyway?
- [ ] Is 10:30am check-in time optimal, or should it be 10:15 or 10:45?
- [ ] Should there be a "warm up" week with easier targets before full system?
- [ ] Worth discussing mirtazapine timing with prescriber? (Strong yes, but user's call)

## Implementation Notes

### Phase 1: Baseline + Meds Timing (Week 1-2)
1. Set up meds reminder at 10:00pm (use Streaks or iOS Reminders)
2. Commit to taking meds within 30min of reminder regardless of work state
3. Track naturally with Watch - don't change alarm or add accountability yet
4. Goal: Establish meds consistency, gather baseline morning data

### Phase 2: Add Morning Check-in (Week 3-4)
1. Add Alarmy or similar with photo/QR requirement
2. Set up escalation to partner (simple text if check-in not done by 10:45)
3. Start logging work-start time
4. Goal: Test if consistent meds + accountability improves mornings

### Phase 3: Iterate (Week 5+)
1. Review data - what patterns emerged?
2. Adjust escalation tiers, check-in time, or mechanism based on failure modes
3. Consider involving research manager if partner escalation isn't sufficient
4. Discuss findings with therapist/prescriber if relevant

### Cold-Bed Mitigation
- Keep robe/slippers next to bed
- Consider heated blanket on timer (though not portable)
- First action after check-in: make hot drink

---

## Current Implementation (as of 2026-01-14)

### Apps in Use
- **Apple Meds** - mirtazapine reminder (already set up)
- **Awake** - push-ups to dismiss alarm (testing)
- **Alarmy** - shake phone to dismiss (testing)

Push-ups (Awake) preferred - harder to do from bed, physical exertion makes going back to bed less appealing.

### Daily Tracking (iOS Shortcut / one-tap)

| Field | When to log |
|-------|-------------|
| Meds time | When mirtazapine taken (Apple Meds handles) |
| Bedtime | When physically getting in bed to sleep |
| Bed-exit time | When feet hit floor, committed to being up |
| Work-start time | When actually begin working |

Optional: Grogginess (1-5), Back-to-bed (yes/no)

Sleep duration/quality comes from Watch automatically.

### Morning Routine
- Brush teeth, wash hair, dress
- ~20-30 min total
- Commute: 5 min
- Target: bed-exit 10:30 → work-start 11:00

If gap between bed-exit and work-start exceeds 30 min, investigate where time is leaking.

### "I Feel Rubbish" Decision Framework

**Key question:** "If I had a meeting in 15 minutes, would I get up?"
- If yes → push through, you'll wake up
- If genuinely no → maybe you need rest

| Feeling | Action |
|---------|--------|
| Groggy but functional | Push through. Coffee. |
| Genuinely exhausted | 30-min timed nap MAX, then up regardless |
| Sick | Rest. Log as sick day. System paused. |

**Core rule:** Once up and checked in, can only go back to bed with a hard 30-min limit. The problem is open-ended "I'll get up when I feel better" → 2+ hours.

**Track:** When you DO push through groggy, how's the day? Test if "rubbish morning → rubbish day" is actually true or just a belief.

### Meetings in Bed
Meetings don't count as "up." Even if taking a 10am meeting from bed, still owe the check-in once meeting ends. Check-in proves feet-on-floor, not "awake and talking."

---

*Spec written via interview on 2026-01-14. Updated with implementation details same day.*
