/*
Copyright (C) 1997-2001 Id Software, Inc.

This program is free software; you can redistribute it and/or
modify it under the terms of the GNU General Public License
as published by the Free Software Foundation; either version 2
of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.

*/
// snd_loc.h -- private interface between the files of the OpenAL sound backend

#include <AL/al.h>
#include <AL/alc.h>
#include <AL/alext.h>

#define NO_LOOP_START       -1
#define MS_PER_SECOND       1000
#define SOUND_VOLUME_FULL   1.0f

typedef struct sfx_s
{
    char    name[MAX_QPATH];
    int     registration_sequence;
    ALuint  buffer;         // 0 = not loaded
    int     length;         // in samples
    int     loopstart;      // NO_LOOP_START or the sample a cue chunk loops back to
    int     rate;
    int     width;          // bytes per sample
    char    *truename;      // aliased sounds load this file instead
} sfx_t;

typedef struct
{
    int     rate;
    int     width;
    int     channels;
    int     loopstart;
    int     samples;
    int     dataofs;        // sample data starts this many bytes from file start
} wavinfo_t;

extern qboolean sound_started;

extern cvar_t   *s_volume;
extern cvar_t   *s_show;

// snd_wav.c
wavinfo_t GetWavinfo (char *name, byte *wav, int wavlength);

// snd_mem.c
qboolean S_LoadSound (sfx_t *sfx);
void S_FreeSound (sfx_t *sfx);

// snd_sfx.c
qboolean S_IsPlayerSoundPlaceholder (const sfx_t *sfx);
sfx_t *S_RegisterPlayerSound (entity_state_t *ent, const char *placeholder);
void S_FreeAllSounds (void);
void S_SoundListCommand (void);

// snd_source.c
void S_StopSource (ALuint source);
void S_PlaceSourceOnListener (ALuint source);
void S_PlaceSourceInWorld (ALuint source, vec3_t origin, float dist_mult);
qboolean S_IsSpatialized (float dist_mult);
qboolean S_IsInRange (vec3_t origin, float dist_mult);

// snd_channel.c
qboolean S_InitChannels (void);
void S_ShutdownChannels (void);
void S_UpdateChannels (void);
void S_StopAllChannels (void);
void S_StopChannelsUsing (sfx_t *sfx);
void S_PrintChannels (void);
void S_PlaySoundCommand (void);

// snd_loop.c
qboolean S_InitLoopSounds (void);
void S_ShutdownLoopSounds (void);
void S_UpdateLoopSounds (void);
void S_StopLoopSounds (void);
void S_StopLoopSoundsUsing (sfx_t *sfx);
void S_PrintLoopSounds (void);

// snd_raw.c
qboolean S_InitRawSamples (void);
void S_ShutdownRawSamples (void);
void S_ClearRawSamples (void);

// cd_music.c streams on the OpenAL context owned by snd_al.c,
// so it has to let go of its objects whenever the context goes away
void Music_SoundShutdown (void);
void Music_SoundRestart (void);
