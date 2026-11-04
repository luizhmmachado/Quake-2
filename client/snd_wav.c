// snd_wav.c -- RIFF/WAVE parser for the game's original sound files

#include "client.h"
#include "snd_loc.h"

#define WAVE_FORMAT_PCM     1
#define RIFF_HEADER_SIZE    8   // 4 byte id + 4 byte length
#define RIFF_FORM_SIZE      12  // "RIFF" header + "WAVE" form type
#define FMT_PCM_SIZE        16
#define CUE_LOOPSTART_OFS   32  // offset of the first cue point's sample position
#define LIST_MARK_ID_OFS    28  // where cooledit stores its "mark" id
#define LIST_MARK_LEN_OFS   24  // and the sample count of the loop

typedef struct
{
    byte    *first;     // first chunk of the list being searched
    byte    *end;
    byte    *next;      // chunk after the last one found
} riffreader_t;

static int ReadLittleShort (const byte *p)
{
    return (short)(p[0] | (p[1] << 8));
}

static int ReadLittleLong (const byte *p)
{
    return p[0] | (p[1] << 8) | (p[2] << 16) | (p[3] << 24);
}

/*
============
Riff_FindNextChunk

Returns the header of the next chunk with the given id, or NULL
============
*/
static byte *Riff_FindNextChunk (riffreader_t *reader, const char *id)
{
    while (reader->next + RIFF_HEADER_SIZE <= reader->end)
    {
        byte *chunk = reader->next;
        int length = ReadLittleLong (chunk + 4);

        if (length < 0)
            return NULL;

        reader->next = chunk + RIFF_HEADER_SIZE + ((length + 1) & ~1);
        if (!strncmp ((char *)chunk, id, 4))
            return chunk;
    }
    return NULL;
}

static byte *Riff_FindChunk (riffreader_t *reader, const char *id)
{
    reader->next = reader->first;
    return Riff_FindNextChunk (reader, id);
}

static qboolean Riff_Fits (const riffreader_t *reader, const byte *chunk, int size)
{
    return chunk + size <= reader->end;
}

/*
============
Wav_ReadLoop

A cue chunk marks where the sound loops back to. If a LIST chunk
follows it, cooledit stores the length of the loop there.
This is not a proper parse, but it works with cooledit...
============
*/
static void Wav_ReadLoop (riffreader_t *reader, wavinfo_t *info)
{
    info->loopstart = NO_LOOP_START;

    byte *cue = Riff_FindChunk (reader, "cue ");
    if (!cue || !Riff_Fits (reader, cue, CUE_LOOPSTART_OFS + 4))
        return;

    info->loopstart = ReadLittleLong (cue + CUE_LOOPSTART_OFS);

    byte *list = Riff_FindNextChunk (reader, "LIST");
    if (list && Riff_Fits (reader, list, LIST_MARK_ID_OFS + 4)
        && !strncmp ((char *)list + LIST_MARK_ID_OFS, "mark", 4))
    {
        info->samples = info->loopstart + ReadLittleLong (list + LIST_MARK_LEN_OFS);
    }
}

/*
============
GetWavinfo

info.channels is 0 when the file can't be used
============
*/
wavinfo_t GetWavinfo (char *name, byte *wav, int wavlength)
{
    wavinfo_t info;
    memset (&info, 0, sizeof(info));

    if (!wav)
        return info;

    riffreader_t reader = { wav, wav + wavlength, wav };

    byte *riff = Riff_FindChunk (&reader, "RIFF");
    if (!riff || !Riff_Fits (&reader, riff, RIFF_FORM_SIZE) || strncmp ((char *)riff + 8, "WAVE", 4))
    {
        Com_Printf ("Missing RIFF/WAVE chunks\n");
        return info;
    }

    // the remaining chunks live inside the RIFF chunk
    reader.first = riff + RIFF_FORM_SIZE;

    byte *fmt = Riff_FindChunk (&reader, "fmt ");
    if (!fmt || !Riff_Fits (&reader, fmt, RIFF_HEADER_SIZE + FMT_PCM_SIZE))
    {
        Com_Printf ("Missing fmt chunk\n");
        return info;
    }

    byte *fmt_data = fmt + RIFF_HEADER_SIZE;
    if (ReadLittleShort (fmt_data) != WAVE_FORMAT_PCM)
    {
        Com_Printf ("Microsoft PCM format only\n");
        return info;
    }

    int channels = ReadLittleShort (fmt_data + 2);
    info.rate = ReadLittleLong (fmt_data + 4);
    info.width = ReadLittleShort (fmt_data + 14) / 8;
    if (info.width != 1 && info.width != 2)
    {
        Com_Printf ("%s: only 8 and 16 bit samples are supported\n", name);
        return info;
    }

    Wav_ReadLoop (&reader, &info);

    byte *data = Riff_FindChunk (&reader, "data");
    if (!data)
    {
        Com_Printf ("Missing data chunk\n");
        return info;
    }

    int data_samples = ReadLittleLong (data + 4) / info.width;
    info.dataofs = (data + RIFF_HEADER_SIZE) - wav;
    if (info.dataofs + data_samples * info.width > wavlength)
    {
        Com_Printf ("%s: data chunk is truncated\n", name);
        return info;
    }

    if (!info.samples)
        info.samples = data_samples;
    else if (data_samples < info.samples)
        Com_Error (ERR_DROP, "Sound %s has a bad loop length", name);

    info.channels = channels;
    return info;
}
