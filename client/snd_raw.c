// snd_raw.c -- streams raw PCM from cinematics through a queue of buffers

#include "client.h"
#include "snd_loc.h"

// about two seconds of cinematic audio, more than that and we fell behind
#define MAX_RAW_BUFFERS     32
#define SIGNED_TO_UNSIGNED_8BIT  0x80

static ALuint raw_source;

static void S_DeleteRawBuffers (ALint count)
{
    for (ALint i = 0; i < count; i++)
    {
        ALuint buffer;
        alSourceUnqueueBuffers (raw_source, 1, &buffer);
        alDeleteBuffers (1, &buffer);
    }
}

static ALint S_RawSourceInt (ALenum param)
{
    ALint value;
    alGetSourcei (raw_source, param, &value);
    return value;
}

static ALenum S_RawFormat (int width, int num_channels)
{
    if (num_channels == 2)
        return width == 2 ? AL_FORMAT_STEREO16 : AL_FORMAT_STEREO8;
    return width == 2 ? AL_FORMAT_MONO16 : AL_FORMAT_MONO8;
}

// returns a copy of the samples in the layout OpenAL expects, free with Z_Free
static byte *S_ConvertRawSamples (const byte *data, int samples, int width, int num_channels)
{
    int size = samples * width * num_channels;
    byte *pcm = Z_Malloc (size);
    memcpy (pcm, data, size);

    if (width == 2)
    {
        for (int i = 0; i < samples * num_channels; i++)
            ((short *)pcm)[i] = LittleShort (((short *)pcm)[i]);
    }
    else if (num_channels == 2)
    {
        // stereo 8 bit cinematic data is signed, OpenAL wants it unsigned
        for (int i = 0; i < size; i++)
            pcm[i] ^= SIGNED_TO_UNSIGNED_8BIT;
    }

    return pcm;
}

qboolean S_InitRawSamples (void)
{
    alGetError ();
    alGenSources (1, &raw_source);
    if (alGetError () != AL_NO_ERROR)
    {
        Com_Printf ("S_InitRawSamples: can't allocate an OpenAL source\n");
        return false;
    }

    S_PlaceSourceOnListener (raw_source);
    return true;
}

void S_ShutdownRawSamples (void)
{
    S_ClearRawSamples ();
    alDeleteSources (1, &raw_source);
    raw_source = 0;
}

void S_ClearRawSamples (void)
{
    alSourceStop (raw_source);
    S_DeleteRawBuffers (S_RawSourceInt (AL_BUFFERS_QUEUED));
}

/*
============
S_RawSamples

Cinematic streaming and voice over network
============
*/
void S_RawSamples (int samples, int rate, int width, int num_channels, byte *data)
{
    if (!sound_started)
        return;

    // recycle what has already been played
    S_DeleteRawBuffers (S_RawSourceInt (AL_BUFFERS_PROCESSED));

    if (S_RawSourceInt (AL_BUFFERS_QUEUED) >= MAX_RAW_BUFFERS)
        return;     // fell too far behind, drop this chunk

    byte *pcm = S_ConvertRawSamples (data, samples, width, num_channels);

    ALuint buffer;
    alGenBuffers (1, &buffer);
    alBufferData (buffer, S_RawFormat (width, num_channels), pcm, samples * width * num_channels, rate);
    alSourceQueueBuffers (raw_source, 1, &buffer);
    Z_Free (pcm);

    if (S_RawSourceInt (AL_SOURCE_STATE) != AL_PLAYING)
        alSourcePlay (raw_source);
}
