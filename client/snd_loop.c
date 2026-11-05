// snd_loop.c -- looping sounds of entities (machines, water, lifts...)
//
// Entities with a ->sound field generate looped sounds that are
// automatically started, stopped and moved as the entities are sent
// to the client. Each entity gets its own source, so the sound comes
// from where the entity is.

#include "client.h"
#include "snd_loc.h"

#define MAX_LOOPSOUNDS          32
#define SOUND_LOOPATTENUATE     0.003f

typedef struct
{
    ALuint      source;
    sfx_t       *sfx;               // NULL = free
    int         entnum;
    qboolean    seen_this_frame;    // entity still emits the sound
} loopsound_t;

static loopsound_t loopsounds[MAX_LOOPSOUNDS];

static void S_StopLoopSound (loopsound_t *loop)
{
    S_StopSource (loop->source);
    loop->sfx = NULL;
    loop->entnum = 0;
    loop->seen_this_frame = false;
}

static loopsound_t *S_FindLoopSound (sfx_t *sfx, int entnum)
{
    for (int i = 0; i < MAX_LOOPSOUNDS; i++)
    {
        if (loopsounds[i].sfx == sfx && loopsounds[i].entnum == entnum)
            return &loopsounds[i];
    }
    return NULL;
}

static loopsound_t *S_FreeLoopSound (void)
{
    for (int i = 0; i < MAX_LOOPSOUNDS; i++)
    {
        if (!loopsounds[i].sfx)
            return &loopsounds[i];
    }
    return NULL;
}

static loopsound_t *S_StartLoopSound (sfx_t *sfx, int entnum, vec3_t origin)
{
    loopsound_t *loop = S_FreeLoopSound ();
    if (!loop)
        return NULL;

    loop->sfx = sfx;
    loop->entnum = entnum;

    // loops of the same sound all play in phase, like in the original mixer
    long long elapsed_samples = (long long)cls.realtime * sfx->rate / MS_PER_SECOND;

    alSourcei (loop->source, AL_BUFFER, sfx->buffer);
    alSourcei (loop->source, AL_LOOPING, AL_TRUE);
    alSourcef (loop->source, AL_GAIN, SOUND_VOLUME_FULL);
    alSourcei (loop->source, AL_SAMPLE_OFFSET, (ALint)(elapsed_samples % sfx->length));
    S_PlaceSourceInWorld (loop->source, origin, SOUND_LOOPATTENUATE);
    alSourcePlay (loop->source);
    return loop;
}

static void S_AddEntityLoopSound (entity_state_t *ent)
{
    sfx_t *sfx = cl.sound_precache[ent->sound];
    if (!sfx || !sfx->buffer)
        return;     // bad sound effect

    if (!S_IsInRange (ent->origin, SOUND_LOOPATTENUATE))
        return;

    loopsound_t *loop = S_FindLoopSound (sfx, ent->number);
    if (loop)
        S_PlaceSourceInWorld (loop->source, ent->origin, SOUND_LOOPATTENUATE);
    else
        loop = S_StartLoopSound (sfx, ent->number, ent->origin);

    if (loop)
        loop->seen_this_frame = true;
}

static qboolean S_LoopSoundsPlay (void)
{
    return !cl_paused->value && cls.state == ca_active && cl.sound_prepped;
}

qboolean S_InitLoopSounds (void)
{
    ALuint sources[MAX_LOOPSOUNDS];

    alGetError ();
    alGenSources (MAX_LOOPSOUNDS, sources);
    if (alGetError () != AL_NO_ERROR)
    {
        Com_Printf ("S_InitLoopSounds: can't allocate %i OpenAL sources\n", MAX_LOOPSOUNDS);
        return false;
    }

    memset (loopsounds, 0, sizeof(loopsounds));
    for (int i = 0; i < MAX_LOOPSOUNDS; i++)
        loopsounds[i].source = sources[i];
    return true;
}

void S_ShutdownLoopSounds (void)
{
    S_StopLoopSounds ();
    for (int i = 0; i < MAX_LOOPSOUNDS; i++)
        alDeleteSources (1, &loopsounds[i].source);
    memset (loopsounds, 0, sizeof(loopsounds));
}

void S_UpdateLoopSounds (void)
{
    for (int i = 0; i < MAX_LOOPSOUNDS; i++)
        loopsounds[i].seen_this_frame = false;

    if (S_LoopSoundsPlay ())
    {
        for (int i = 0; i < cl.frame.num_entities; i++)
        {
            int num = (cl.frame.parse_entities + i) & (MAX_PARSE_ENTITIES - 1);
            entity_state_t *ent = &cl_parse_entities[num];
            if (ent->sound)
                S_AddEntityLoopSound (ent);
        }
    }

    // entities that stopped making their sound
    for (int i = 0; i < MAX_LOOPSOUNDS; i++)
    {
        if (loopsounds[i].sfx && !loopsounds[i].seen_this_frame)
            S_StopLoopSound (&loopsounds[i]);
    }
}

void S_StopLoopSounds (void)
{
    for (int i = 0; i < MAX_LOOPSOUNDS; i++)
        S_StopLoopSound (&loopsounds[i]);
}

void S_StopLoopSoundsUsing (sfx_t *sfx)
{
    for (int i = 0; i < MAX_LOOPSOUNDS; i++)
    {
        if (loopsounds[i].sfx == sfx)
            S_StopLoopSound (&loopsounds[i]);
    }
}

void S_PrintLoopSounds (void)
{
    for (int i = 0; i < MAX_LOOPSOUNDS; i++)
    {
        if (loopsounds[i].sfx)
            Com_Printf ("%3i %s (loop)\n", loopsounds[i].entnum, loopsounds[i].sfx->name);
    }
}
