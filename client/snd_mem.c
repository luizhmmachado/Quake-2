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
// snd_mem.c -- loads the original WAV files into OpenAL buffers

#include "client.h"
#include "snd_loc.h"

/*
==============
S_UploadSound

Hands the original PCM data to OpenAL at its native rate and width.
8 bit WAV data is unsigned, which is what AL_FORMAT_MONO8 expects.
==============
*/
static qboolean S_UploadSound (sfx_t *sfx, const wavinfo_t *info, byte *pcm)
{
    ALenum format = AL_FORMAT_MONO8;

    if (info->width == 2)
    {
        format = AL_FORMAT_MONO16;
        for (int i = 0; i < info->samples; i++)
            ((short *)pcm)[i] = LittleShort (((short *)pcm)[i]);
    }

    alGetError ();
    alGenBuffers (1, &sfx->buffer);
    alBufferData (sfx->buffer, format, pcm, info->samples * info->width, info->rate);
    if (alGetError () != AL_NO_ERROR)
    {
        Com_Printf ("S_LoadSound: OpenAL rejected %s\n", sfx->name);
        alDeleteBuffers (1, &sfx->buffer);
        sfx->buffer = 0;
        return false;
    }

    // sounds with a cue chunk restart from loopstart instead of stopping
    if (info->loopstart != NO_LOOP_START && alIsExtensionPresent ("AL_SOFT_loop_points"))
    {
        ALint loop_points[2] = { info->loopstart, info->samples };
        alBufferiv (sfx->buffer, AL_LOOP_POINTS_SOFT, loop_points);
    }

    sfx->length = info->samples;
    sfx->loopstart = info->loopstart;
    sfx->rate = info->rate;
    sfx->width = info->width;

    return true;
}

static void S_SoundPath (const sfx_t *sfx, char *path, int size)
{
    const char *name = sfx->truename ? sfx->truename : sfx->name;

    // '#' marks a path outside of the sound directory
    if (name[0] == '#')
        Com_sprintf (path, size, "%s", &name[1]);
    else
        Com_sprintf (path, size, "sound/%s", name);
}

/*
==============
S_LoadSound

Returns true once the sound has an OpenAL buffer
==============
*/
qboolean S_LoadSound (sfx_t *sfx)
{
    // resolved per player model by S_RegisterPlayerSound
    if (S_IsPlayerSoundPlaceholder (sfx))
        return false;

    if (sfx->buffer)
        return true;

    char path[MAX_QPATH];
    S_SoundPath (sfx, path, sizeof(path));

    byte *data;
    int size = FS_LoadFile (path, (void **)&data);
    if (!data)
    {
        Com_DPrintf ("Couldn't load %s\n", path);
        return false;
    }

    wavinfo_t info = GetWavinfo (sfx->name, data, size);
    qboolean loaded = false;
    if (info.channels == 1)
        loaded = S_UploadSound (sfx, &info, data + info.dataofs);
    else if (info.channels > 1)
        Com_Printf ("%s is a stereo sample\n", sfx->name);

    FS_FreeFile (data);

    return loaded;
}

/*
==============
S_FreeSound
==============
*/
void S_FreeSound (sfx_t *sfx)
{
    if (!sfx->buffer)
        return;

    // a buffer can't be deleted while a source still holds it
    S_StopChannelsUsing (sfx);
    S_StopLoopSoundsUsing (sfx);

    alDeleteBuffers (1, &sfx->buffer);
    sfx->buffer = 0;
}
