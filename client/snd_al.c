// snd_al.c -- OpenAL Soft device, HRTF, listener and the sound.h entry points
//
// The original WAV files, volumes and attenuation values are kept,
// only mixing and spatialization moved from the software mixer to OpenAL.

#include "client.h"
#include "snd_loc.h"

// s_hrtf values, anything else lets OpenAL decide
#define HRTF_OFF    0
#define HRTF_ON     1

#define HRTF_ATTRIBUTE_COUNT    3

qboolean    sound_started = false;

cvar_t      *s_volume;
cvar_t      *s_show;
static cvar_t *s_hrtf;
static cvar_t *s_device;

static ALCdevice    *al_device;
static ALCcontext   *al_context;
static qboolean     hrtf_supported;
static LPALCRESETDEVICESOFT qalcResetDeviceSOFT;

static qboolean     window_active = true;


/*
===============================================================================

HRTF

===============================================================================
*/

static const char *S_HrtfStatus (void)
{
    if (!hrtf_supported)
        return "not supported";

    ALCint status;
    alcGetIntegerv (al_device, ALC_HRTF_STATUS_SOFT, 1, &status);
    switch (status)
    {
    case ALC_HRTF_DISABLED_SOFT:            return "disabled";
    case ALC_HRTF_ENABLED_SOFT:             return "enabled";
    case ALC_HRTF_DENIED_SOFT:              return "denied";
    case ALC_HRTF_REQUIRED_SOFT:            return "required";
    case ALC_HRTF_HEADPHONES_DETECTED_SOFT: return "enabled (headphones detected)";
    case ALC_HRTF_UNSUPPORTED_FORMAT_SOFT:  return "unsupported output format";
    default:                                return "unknown";
    }
}

// zero terminated ALC attribute list for the current s_hrtf value
static void S_FillHrtfAttributes (ALCint attributes[HRTF_ATTRIBUTE_COUNT])
{
    attributes[0] = 0;

    if (!hrtf_supported)
        return;

    attributes[0] = ALC_HRTF_SOFT;
    if (s_hrtf->value == HRTF_OFF)
        attributes[1] = ALC_FALSE;
    else if (s_hrtf->value == HRTF_ON)
        attributes[1] = ALC_TRUE;
    else
        attributes[1] = ALC_DONT_CARE_SOFT;
    attributes[2] = 0;
}

static void S_ApplyHrtf (void)
{
    s_hrtf->modified = false;

    if (!qalcResetDeviceSOFT)
        return;

    ALCint attributes[HRTF_ATTRIBUTE_COUNT];
    S_FillHrtfAttributes (attributes);
    if (!qalcResetDeviceSOFT (al_device, attributes))
        Com_Printf ("S_ApplyHrtf: alcResetDeviceSOFT failed\n");
    Com_Printf ("HRTF %s\n", S_HrtfStatus ());
}


/*
===============================================================================

Device and context

===============================================================================
*/

static void S_CloseDevice (void)
{
    alcMakeContextCurrent (NULL);
    if (al_context)
        alcDestroyContext (al_context);
    if (al_device)
        alcCloseDevice (al_device);
    al_context = NULL;
    al_device = NULL;
    qalcResetDeviceSOFT = NULL;
}

static qboolean S_OpenDevice (void)
{
    al_device = alcOpenDevice (s_device->string[0] ? s_device->string : NULL);
    if (!al_device)
    {
        Com_Printf ("S_Init: can't open OpenAL device \"%s\"\n", s_device->string);
        return false;
    }

    hrtf_supported = alcIsExtensionPresent (al_device, "ALC_SOFT_HRTF");
    if (hrtf_supported)
        qalcResetDeviceSOFT = (LPALCRESETDEVICESOFT)alcGetProcAddress (al_device, "alcResetDeviceSOFT");

    ALCint attributes[HRTF_ATTRIBUTE_COUNT];
    S_FillHrtfAttributes (attributes);
    s_hrtf->modified = false;

    al_context = alcCreateContext (al_device, attributes);
    if (!al_context || !alcMakeContextCurrent (al_context))
    {
        Com_Printf ("S_Init: can't create OpenAL context\n");
        S_CloseDevice ();
        return false;
    }

    // the original attenuation curve, see snd_source.c.
    // doppler was never part of the game.
    alDistanceModel (AL_LINEAR_DISTANCE_CLAMPED);
    alDopplerFactor (0);

    return true;
}

static qboolean S_InitSources (void)
{
    if (!S_InitChannels ())
        return false;

    if (!S_InitLoopSounds ())
    {
        S_ShutdownChannels ();
        return false;
    }

    if (!S_InitRawSamples ())
    {
        S_ShutdownLoopSounds ();
        S_ShutdownChannels ();
        return false;
    }

    return true;
}

static void S_ShutdownSources (void)
{
    S_ShutdownRawSamples ();
    S_ShutdownLoopSounds ();
    S_ShutdownChannels ();
}


/*
===============================================================================

Listener

===============================================================================
*/

static void S_UpdateListener (vec3_t origin, vec3_t forward, vec3_t up)
{
    // stay quiet while the loading plaque is up or the window is in the background
    if (cls.disable_screen || !window_active)
        alListenerf (AL_GAIN, 0);
    else
        alListenerf (AL_GAIN, s_volume->value);

    // Quake and OpenAL are both right handed, so the view
    // vectors can be handed over without any conversion
    ALfloat orientation[6] = {
        forward[0], forward[1], forward[2],
        up[0], up[1], up[2]
    };
    alListenerfv (AL_POSITION, origin);
    alListenerfv (AL_ORIENTATION, orientation);
}


/*
===============================================================================

Console commands

===============================================================================
*/

static void S_SoundInfoCommand (void)
{
    if (!sound_started)
    {
        Com_Printf ("sound system not started\n");
        return;
    }

    ALCint rate;
    alcGetIntegerv (al_device, ALC_FREQUENCY, 1, &rate);

    Com_Printf ("AL_VENDOR:   %s\n", alGetString (AL_VENDOR));
    Com_Printf ("AL_RENDERER: %s\n", alGetString (AL_RENDERER));
    Com_Printf ("AL_VERSION:  %s\n", alGetString (AL_VERSION));
    Com_Printf ("device:      %s\n", alcGetString (al_device, ALC_ALL_DEVICES_SPECIFIER));
    Com_Printf ("rate:        %i Hz\n", rate);
    Com_Printf ("HRTF:        %s\n", S_HrtfStatus ());
}

static void S_AddCommands (void)
{
    Cmd_AddCommand ("play", S_PlaySoundCommand);
    Cmd_AddCommand ("stopsound", S_StopAllSounds);
    Cmd_AddCommand ("soundlist", S_SoundListCommand);
    Cmd_AddCommand ("soundinfo", S_SoundInfoCommand);
}

static void S_RemoveCommands (void)
{
    Cmd_RemoveCommand ("play");
    Cmd_RemoveCommand ("stopsound");
    Cmd_RemoveCommand ("soundlist");
    Cmd_RemoveCommand ("soundinfo");
}


/*
===============================================================================

Public interface (sound.h)

===============================================================================
*/

void S_Init (void)
{
    Com_Printf ("\n------- sound initialization -------\n");

    cvar_t *initsound = Cvar_Get ("s_initsound", "1", 0);
    if (!initsound->value)
    {
        Com_Printf ("not initializing.\n");
        Com_Printf ("------------------------------------\n");
        return;
    }

    s_volume = Cvar_Get ("s_volume", "0.7", CVAR_ARCHIVE);
    s_show = Cvar_Get ("s_show", "0", 0);
    s_hrtf = Cvar_Get ("s_hrtf", "-1", CVAR_ARCHIVE);
    s_device = Cvar_Get ("s_device", "", CVAR_ARCHIVE);

    if (S_OpenDevice ())
    {
        if (S_InitSources ())
        {
            sound_started = true;
            S_AddCommands ();

            Com_Printf ("OpenAL device: %s\n", alcGetString (al_device, ALC_ALL_DEVICES_SPECIFIER));
            Com_Printf ("HRTF %s\n", S_HrtfStatus ());

            Music_SoundRestart ();
        }
        else
            S_CloseDevice ();
    }

    Com_Printf ("------------------------------------\n");
}

void S_Shutdown (void)
{
    if (!sound_started)
        return;

    Music_SoundShutdown ();
    S_RemoveCommands ();

    S_ShutdownSources ();
    S_FreeAllSounds ();
    S_CloseDevice ();

    sound_started = false;
}

void S_StopAllSounds (void)
{
    if (!sound_started)
        return;

    S_StopAllChannels ();
    S_StopLoopSounds ();
    S_ClearRawSamples ();
}

// the window lost or gained focus
void S_Activate (qboolean active)
{
    window_active = active;
}

/*
============
S_Update

Called once each time through the main loop
============
*/
void S_Update (vec3_t origin, vec3_t forward, vec3_t right, vec3_t up)
{
    if (!sound_started)
        return;

    if (s_hrtf->modified)
        S_ApplyHrtf ();

    S_UpdateListener (origin, forward, up);
    S_UpdateChannels ();
    S_UpdateLoopSounds ();

    if (s_show->value)
    {
        S_PrintChannels ();
        S_PrintLoopSounds ();
    }
}
