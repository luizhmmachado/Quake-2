// snd_source.c -- placement and attenuation of OpenAL sources
//
// The original mixer scaled the volume by
//     1 - (dist - SOUND_FULLVOLUME) * dist_mult
// clamped to [0,1]. AL_LINEAR_DISTANCE_CLAMPED (set up in snd_al.c)
// with the parameters below gives exactly the same curve.

#include "client.h"
#include "snd_loc.h"

// only begin attenuating sound volumes when outside the FULLVOLUME range
#define SOUND_FULLVOLUME    80

static float S_MaxDistance (float dist_mult)
{
    return SOUND_FULLVOLUME + 1.0f / dist_mult;
}

void S_StopSource (ALuint source)
{
    alSourceStop (source);
    alSourcei (source, AL_BUFFER, 0);
}

// sounds without attenuation, or played outside of a level, are not spatialized
qboolean S_IsSpatialized (float dist_mult)
{
    return dist_mult && cls.state == ca_active;
}

void S_PlaceSourceOnListener (ALuint source)
{
    alSourcei (source, AL_SOURCE_RELATIVE, AL_TRUE);
    alSource3f (source, AL_POSITION, 0, 0, 0);
    alSourcef (source, AL_ROLLOFF_FACTOR, 0);
}

void S_PlaceSourceInWorld (ALuint source, vec3_t origin, float dist_mult)
{
    alSourcei (source, AL_SOURCE_RELATIVE, AL_FALSE);
    alSourcefv (source, AL_POSITION, origin);
    alSourcef (source, AL_REFERENCE_DISTANCE, SOUND_FULLVOLUME);
    alSourcef (source, AL_MAX_DISTANCE, S_MaxDistance (dist_mult));
    alSourcef (source, AL_ROLLOFF_FACTOR, 1);
}

// the original mixer dropped sounds whose volume fell to zero
qboolean S_IsInRange (vec3_t origin, float dist_mult)
{
    vec3_t delta;
    VectorSubtract (origin, cl.refdef.vieworg, delta);
    return VectorLength (delta) < S_MaxDistance (dist_mult);
}
