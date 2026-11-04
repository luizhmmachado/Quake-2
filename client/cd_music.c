// cd_music.c -- plays the soundtrack from music/ instead of an audio CD
//
// Keeps the CDAudio_* interface of cdaudio.h, so the rest of the client
// still asks for "CD tracks". Track N is looked up as music/NN.ogg or
// music/trackNN.ogg (also .mp3, .flac and .wav), decoded by SDL_sound and
// streamed through an OpenAL source that is not spatialized.

#include <SDL_sound.h>

#include "client.h"
#include "snd_loc.h"

#define MAX_TRACKS              100

#define NUM_STREAM_BUFFERS      8
#define STREAM_BUFFER_SIZE      16384   // ~93ms of 44.1kHz 16 bit stereo
#define MUSIC_RATE              44100
#define MUSIC_CHANNELS          2

typedef struct
{
    Sound_Sample    *sample;            // NULL = nothing open
    void            *file_data;         // FS_LoadFile buffer the sample decodes from
    ALuint          source;
    ALuint          buffers[NUM_STREAM_BUFFERS];
} musicstream_t;

static char *track_name_formats[] ={ "music/%02i.%s", "music/track%02i.%s" };
static const char *track_extensions[] = { "ogg", "mp3", "flac", "wav" };

static musicstream_t stream;

static qboolean initialized;
static qboolean enabled = true;
static qboolean paused;
static qboolean looping;
static int      current_track;      // 0 = no track wanted
static int      remap[MAX_TRACKS];

static cvar_t   *cd_volume;
static cvar_t   *cd_nocd;


/*
===============================================================================

Decoding and streaming

===============================================================================
*/

static void *Music_LoadTrackFile (int track, const char **extension, int *size)
{
    for (int f = 0; f < sizeof(track_name_formats) / sizeof(track_name_formats[0]); f++)
    {
        for (int e = 0; e < sizeof(track_extensions) / sizeof(track_extensions[0]); e++)
        {
            char path[MAX_QPATH];
            Com_sprintf (path, sizeof(path), track_name_formats[f], track, track_extensions[e]);

            void *data;
            *size = FS_LoadFile (path, &data);
            if (data)
            {
                *extension = track_extensions[e];
                return data;
            }
        }
    }
    return NULL;
}

/*
==================
Music_FillBuffer

Decodes the next block into buffer. Returns false when there
is nothing left to play.
==================
*/
static qboolean Music_FillBuffer (ALuint buffer)
{
    Uint32 decoded = Sound_Decode (stream.sample);

    if (!decoded && looping && (stream.sample->flags & SOUND_SAMPLEFLAG_EOF))
    {
        Sound_Rewind (stream.sample);
        decoded = Sound_Decode (stream.sample);
    }

    if (!decoded)
    {
        if (stream.sample->flags & SOUND_SAMPLEFLAG_ERROR)
            Com_Printf ("Music: decoding error: %s\n", Sound_GetError ());
        return false;
    }

    alBufferData (buffer, AL_FORMAT_STEREO16, stream.sample->buffer, decoded, MUSIC_RATE);
    return true;
}

static ALint Music_SourceInt (ALenum param)
{
    ALint value;
    alGetSourcei (stream.source, param, &value);
    return value;
}

static void Music_Close (void)
{
    if (!stream.sample)
        return;

    alSourceStop (stream.source);
    alSourcei (stream.source, AL_BUFFER, 0);
    alDeleteSources (1, &stream.source);
    alDeleteBuffers (NUM_STREAM_BUFFERS, stream.buffers);

    Sound_FreeSample (stream.sample);
    FS_FreeFile (stream.file_data);

    memset (&stream, 0, sizeof(stream));
}

static qboolean Music_Open (int track)
{
    const char *extension;
    int size;
    void *data = Music_LoadTrackFile (track, &extension, &size);
    if (!data)
    {
        Com_DPrintf ("Music: track %i not found in music/\n", track);
        return false;
    }

    Sound_AudioInfo desired = { AUDIO_S16SYS, MUSIC_CHANNELS, MUSIC_RATE };
    SDL_RWops *rw = SDL_RWFromConstMem (data, size);
    Sound_Sample *sample = Sound_NewSample (rw, extension, &desired, STREAM_BUFFER_SIZE);
    if (!sample)
    {
        Com_Printf ("Music: can't decode track %i: %s\n", track, Sound_GetError ());
        FS_FreeFile (data);
        return false;
    }

    alGetError ();
    alGenSources (1, &stream.source);
    alGenBuffers (NUM_STREAM_BUFFERS, stream.buffers);
    if (alGetError () != AL_NO_ERROR)
    {
        Com_Printf ("Music: can't allocate OpenAL objects\n");
        Sound_FreeSample (sample);
        FS_FreeFile (data);
        memset (&stream, 0, sizeof(stream));
        return false;
    }

    stream.sample = sample;
    stream.file_data = data;

    S_PlaceSourceOnListener (stream.source);
    alSourcef (stream.source, AL_GAIN, cd_volume->value);

    for (int i = 0; i < NUM_STREAM_BUFFERS; i++)
    {
        if (!Music_FillBuffer (stream.buffers[i]))
            break;
        alSourceQueueBuffers (stream.source, 1, &stream.buffers[i]);
    }

    if (!paused)
        alSourcePlay (stream.source);
    return true;
}

static qboolean Music_ShouldPlay (void)
{
    return initialized && enabled && current_track && sound_started && !cd_nocd->value;
}

/*
==================
Music_Stream

Refills the buffers that finished playing
==================
*/
static void Music_Stream (void)
{
    alSourcef (stream.source, AL_GAIN, cd_volume->value);

    for (ALint processed = Music_SourceInt (AL_BUFFERS_PROCESSED); processed > 0; processed--)
    {
        ALuint buffer;
        alSourceUnqueueBuffers (stream.source, 1, &buffer);
        if (Music_FillBuffer (buffer))
            alSourceQueueBuffers (stream.source, 1, &buffer);
    }

    if (!Music_SourceInt (AL_BUFFERS_QUEUED))
    {
        // the track ended and doesn't loop
        Music_Close ();
        current_track = 0;
        return;
    }

    // a long frame can drain the queue: the source stops even though
    // there is more to play, so start it again
    if (!paused && Music_SourceInt (AL_SOURCE_STATE) != AL_PLAYING)
        alSourcePlay (stream.source);
}


/*
===============================================================================

Shared OpenAL context (snd_al.c)

===============================================================================
*/

void Music_SoundShutdown (void)
{
    Music_Close ();
}

void Music_SoundRestart (void)
{
    if (Music_ShouldPlay () && !stream.sample)
        Music_Open (current_track);
}


/*
===============================================================================

Public interface (cdaudio.h)

===============================================================================
*/

static void CDAudio_Pause (void)
{
    paused = true;
    if (stream.sample)
        alSourcePause (stream.source);
}

static void CDAudio_Resume (void)
{
    paused = false;
    if (stream.sample)
        alSourcePlay (stream.source);
}

void CDAudio_Play (int track, qboolean loop)
{
    if (!initialized || !enabled)
        return;

    if (track < 1 || track >= MAX_TRACKS)
    {
        Com_DPrintf ("CDAudio: Bad track number %i.\n", track);
        return;
    }
    track = remap[track];

    if (stream.sample && current_track == track)
        return;

    CDAudio_Stop ();

    current_track = track;
    looping = loop;
    paused = false;

    if (Music_ShouldPlay ())
        Music_Open (track);
}

void CDAudio_Stop (void)
{
    if (!initialized)
        return;

    Music_Close ();
    current_track = 0;
}

void CDAudio_Update (void)
{
    if (!initialized)
        return;

    if (!Music_ShouldPlay ())
    {
        // cd_nocd can be switched from the options menu at any time
        Music_Close ();
        return;
    }

    if (!stream.sample && !Music_Open (current_track))
    {
        current_track = 0;
        return;
    }

    Music_Stream ();
}

void CDAudio_Activate (qboolean active)
{
    if (active)
        CDAudio_Resume ();
    else
        CDAudio_Pause ();
}

static void CDAudio_ResetRemap (void)
{
    for (int i = 0; i < MAX_TRACKS; i++)
        remap[i] = i;
}

static void CDAudio_PrintInfo (void)
{
    if (current_track)
        Com_Printf ("%s %s track %i\n", paused ? "Paused" : "Currently",
            looping ? "looping" : "playing", current_track);
    else
        Com_Printf ("No track playing\n");
    Com_Printf ("Volume is %f\n", cd_volume->value);
}

static void CDAudio_Command (void)
{
    if (Cmd_Argc () < 2)
        return;

    char *command = Cmd_Argv (1);

    if (!Q_strcasecmp (command, "on"))
        enabled = true;
    else if (!Q_strcasecmp (command, "off"))
    {
        CDAudio_Stop ();
        enabled = false;
    }
    else if (!Q_strcasecmp (command, "reset"))
    {
        enabled = true;
        CDAudio_Stop ();
        CDAudio_ResetRemap ();
    }
    else if (!Q_strcasecmp (command, "remap"))
    {
        int count = Cmd_Argc () - 2;
        if (count <= 0)
        {
            for (int i = 1; i < MAX_TRACKS; i++)
            {
                if (remap[i] != i)
                    Com_Printf ("  %i -> %i\n", i, remap[i]);
            }
            return;
        }
        for (int i = 1; i <= count && i < MAX_TRACKS; i++)
            remap[i] = atoi (Cmd_Argv (i + 1));
    }
    else if (!Q_strcasecmp (command, "play"))
        CDAudio_Play (atoi (Cmd_Argv (2)), false);
    else if (!Q_strcasecmp (command, "loop"))
        CDAudio_Play (atoi (Cmd_Argv (2)), true);
    else if (!Q_strcasecmp (command, "stop"))
        CDAudio_Stop ();
    else if (!Q_strcasecmp (command, "pause"))
        CDAudio_Pause ();
    else if (!Q_strcasecmp (command, "resume"))
        CDAudio_Resume ();
    else if (!Q_strcasecmp (command, "info"))
        CDAudio_PrintInfo ();
}

int CDAudio_Init (void)
{
    cvar_t *nocdaudio = Cvar_Get ("nocdaudio", "0", CVAR_NOSET);
    if (nocdaudio->value)
        return -1;

    cd_nocd = Cvar_Get ("cd_nocd", "0", CVAR_ARCHIVE);
    cd_volume = Cvar_Get ("cd_volume", "1", CVAR_ARCHIVE);

    if (!Sound_Init ())
    {
        Com_Printf ("CDAudio_Init: SDL_sound failed: %s\n", Sound_GetError ());
        return -1;
    }

    CDAudio_ResetRemap ();
    enabled = true;
    initialized = true;

    Cmd_AddCommand ("cd", CDAudio_Command);

    Com_Printf ("Music from music/ initialized\n");
    return 0;
}

void CDAudio_Shutdown (void)
{
    if (!initialized)
        return;

    CDAudio_Stop ();
    Cmd_RemoveCommand ("cd");
    Sound_Quit ();
    initialized = false;
}
