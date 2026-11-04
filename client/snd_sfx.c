// snd_sfx.c -- registry of known sounds and per level registration

#include "client.h"
#include "snd_loc.h"

// during registration it is possible to have more sounds
// than could actually be referenced during gameplay,
// because we don't want to free anything until we are
// sure we won't need it.
#define MAX_SFX     (MAX_SOUNDS * 2)

// names starting with this are placeholders for a per player model sound
#define PLAYER_SOUND_PREFIX     '*'
#define DEFAULT_PLAYER_MODEL    "male"

static sfx_t    known_sfx[MAX_SFX];
static int      num_sfx;

static int      registration_sequence;
static qboolean registering;

static sfx_t *S_AllocSfx (const char *name)
{
    int i = 0;
    while (i < num_sfx && known_sfx[i].name[0])
        i++;

    if (i == num_sfx)
    {
        if (num_sfx == MAX_SFX)
            Com_Error (ERR_FATAL, "S_FindName: out of sfx_t");
        num_sfx++;
    }

    sfx_t *sfx = &known_sfx[i];
    memset (sfx, 0, sizeof(*sfx));
    strcpy (sfx->name, name);
    sfx->registration_sequence = registration_sequence;
    return sfx;
}

static void S_ReleaseSfx (sfx_t *sfx)
{
    S_FreeSound (sfx);
    if (sfx->truename)
        Z_Free (sfx->truename);
    memset (sfx, 0, sizeof(*sfx));
}

void S_FreeAllSounds (void)
{
    for (int i = 0; i < num_sfx; i++)
    {
        if (known_sfx[i].name[0])
            S_ReleaseSfx (&known_sfx[i]);
    }
    num_sfx = 0;
}

qboolean S_IsPlayerSoundPlaceholder (const sfx_t *sfx)
{
    return sfx->name[0] == PLAYER_SOUND_PREFIX;
}

sfx_t *S_FindName (char *name, qboolean create)
{
    if (!name)
        Com_Error (ERR_FATAL, "S_FindName: NULL\n");
    if (!name[0])
        Com_Error (ERR_FATAL, "S_FindName: empty name\n");
    if (strlen (name) >= MAX_QPATH)
        Com_Error (ERR_FATAL, "Sound name too long: %s", name);

    for (int i = 0; i < num_sfx; i++)
    {
        if (!strcmp (known_sfx[i].name, name))
            return &known_sfx[i];
    }

    if (!create)
        return NULL;

    return S_AllocSfx (name);
}

// a sound registered under one name that loads another file
static sfx_t *S_AliasName (const char *aliasname, const char *truename)
{
    sfx_t *sfx = S_AllocSfx (aliasname);
    sfx->truename = Z_Malloc (MAX_QPATH);
    strcpy (sfx->truename, truename);
    return sfx;
}

void S_BeginRegistration (void)
{
    registration_sequence++;
    registering = true;
}

sfx_t *S_RegisterSound (char *name)
{
    if (!sound_started)
        return NULL;

    sfx_t *sfx = S_FindName (name, true);
    sfx->registration_sequence = registration_sequence;

    // during registration everything is loaded at once in S_EndRegistration
    if (!registering)
        S_LoadSound (sfx);

    return sfx;
}

void S_EndRegistration (void)
{
    // free any sounds not from this registration sequence, it is possible
    // to have leftovers from a server that didn't finish loading
    for (int i = 0; i < num_sfx; i++)
    {
        sfx_t *sfx = &known_sfx[i];
        if (sfx->name[0] && sfx->registration_sequence != registration_sequence)
            S_ReleaseSfx (sfx);
    }

    for (int i = 0; i < num_sfx; i++)
    {
        if (known_sfx[i].name[0])
            S_LoadSound (&known_sfx[i]);
    }

    registering = false;
}

// the model name is the part of the skin configstring between '\' and '/'
static void S_PlayerModel (int entnum, char *model, int size)
{
    model[0] = 0;

    const char *skin = cl.configstrings[CS_PLAYERSKINS + entnum - 1];
    const char *p = strchr (skin, '\\');
    if (p)
    {
        Com_sprintf (model, size, "%s", p + 1);
        char *slash = strchr (model, '/');
        if (slash)
            *slash = 0;
    }

    if (!model[0])
        Com_sprintf (model, size, DEFAULT_PLAYER_MODEL);
}

/*
==================
S_RegisterPlayerSound

Pain, death, jump... sounds are named "*name" and every player model
can have its own version of them. Resolves the placeholder to the
sound of the entity's model, or to the default model's sound when
that model doesn't ship one.
==================
*/
sfx_t *S_RegisterPlayerSound (entity_state_t *ent, const char *placeholder)
{
    const char *base = placeholder + 1;

    char model[MAX_QPATH];
    S_PlayerModel (ent->number, model, sizeof(model));

    // '#' makes S_LoadSound look outside of the sound directory
    char model_sound[MAX_QPATH];
    Com_sprintf (model_sound, sizeof(model_sound), "#players/%s/%s", model, base);
    sfx_t *sfx = S_FindName (model_sound, false);
    if (sfx)
        return sfx;

    FILE *f;
    FS_FOpenFile (&model_sound[1], &f);
    if (f)
    {
        FS_FCloseFile (f);
        return S_RegisterSound (model_sound);
    }

    char default_sound[MAX_QPATH];
    Com_sprintf (default_sound, sizeof(default_sound), "player/%s/%s", DEFAULT_PLAYER_MODEL, base);
    return S_AliasName (model_sound, default_sound);
}

void S_SoundListCommand (void)
{
    int total = 0;

    for (int i = 0; i < num_sfx; i++)
    {
        const sfx_t *sfx = &known_sfx[i];
        if (!sfx->registration_sequence)
            continue;

        if (sfx->buffer)
        {
            int size = sfx->length * sfx->width;
            total += size;
            Com_Printf ("%s(%2db %5dHz) %6i : %s\n",
                sfx->loopstart != NO_LOOP_START ? "L" : " ",
                sfx->width * 8, sfx->rate, size, sfx->name);
        }
        else if (S_IsPlayerSoundPlaceholder (sfx))
            Com_Printf ("  placeholder : %s\n", sfx->name);
        else
            Com_Printf ("  not loaded  : %s\n", sfx->name);
    }
    Com_Printf ("Total resident: %i\n", total);
}
