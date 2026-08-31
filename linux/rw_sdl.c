#include <SDL2/SDL.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Headers internos do Quake II */
#include "../ref_soft/r_local.h"
#include "../client/keys.h"
#include "rw_linux.h"

void SWimp_InitPalette(void);              // Conserta o warning da paleta
extern void CL_ApplyMouse(int mx, int my); // Nossa ponte com o cliente!

extern viddef_t viddef;

static SDL_Window *window = NULL;
static SDL_Renderer *renderer = NULL;
static SDL_Texture *texture = NULL;

static uint32_t argb_buffer[1600 * 1200];
static uint32_t current_palette[256];

/* Buffers de entrada do mouse para a engine */
int mx = 0;
int my = 0;

/* Protótipos das funções da interface RW_IN */
void RW_IN_Init(void);
void RW_IN_Shutdown(void);
void RW_IN_Commands(void);
void RW_IN_Move(usercmd_t *cmd);
void RW_IN_Frame(void);
void RW_IN_Activate(qboolean active);

typedef struct {
    void (*Init)(void);
    void (*Shutdown)(void);
    void (*Commands)(void);
    void (*Move)(usercmd_t *cmd);
    void (*Frame)(void);
    void (*Activate)(qboolean active);
} rw_in_t;

rw_in_t rw_in = {
    RW_IN_Init,
    RW_IN_Shutdown,
    RW_IN_Commands,
    RW_IN_Move,
    RW_IN_Frame,
    RW_IN_Activate
};

void RW_IN_Init(void) {}
void RW_IN_Shutdown(void) {}
void RW_IN_Commands(void) {}
void RW_IN_Move(usercmd_t *cmd)
{
    {
    if (!SDL_GetRelativeMouseMode()) return;

    // Envia o movimento para o lado do cliente resolver
    CL_ApplyMouse(mx, my);

    // Zera o acumulador
    mx = 0;
    my = 0;
}
}
void RW_IN_Activate(qboolean active) {}
void RW_IN_Frame(void)
{
    KBD_Update();
}

static Key_Event_fp_t Key_Event_fp = NULL;

void KBD_Init(Key_Event_fp_t fp)
{
    //ri.Con_Printf(PRINT_ALL, "DEBUG: KBD_Init\n");

    Key_Event_fp = fp;

    //ri.Con_Printf(
        //PRINT_ALL,
        //"DEBUG: Key_Event_fp=%p\n",
        //(void *)Key_Event_fp
    //);
}

void KBD_Update(void)
{
    //printf(">>> SDL Sys_SendKeyEvents <<<\n");
    SDL_Event event;

    //ri.Con_Printf(PRINT_ALL, "DEBUG: Sys_SendKeyEvents BEGIN\n");

    while (SDL_PollEvent(&event)) {

        //ri.Con_Printf(
          //  PRINT_ALL,
            //"DEBUG: SDL event type=%u\n",
            //event.type
        //);

        switch (event.type) {

            case SDL_QUIT:
                //ri.Con_Printf(PRINT_ALL, "DEBUG: SDL_QUIT\n");
                Cbuf_AddText("quit\n");
                break;

            case SDL_MOUSEMOTION:
                //ri.Con_Printf(PRINT_ALL, "DEBUG: SDL_MOUSEMOTION\n");

                if (SDL_GetRelativeMouseMode()) {
                    mx += event.motion.xrel;
                    my += event.motion.yrel;
                }

                break;

            case SDL_KEYDOWN:
            case SDL_KEYUP: {
                //ri.Con_Printf(PRINT_ALL, "DEBUG: SDL_KEY\n");


                int qkey = MapKey(event.key.keysym.sym);

				if (event.type == SDL_KEYDOWN) {
            		if (qkey == K_ESCAPE || qkey == '`') {
			        	SDL_SetRelativeMouseMode(SDL_FALSE);
                	}
           		}

                //ri.Con_Printf(
                  //  PRINT_ALL,
                    //"DEBUG: qkey=%d\n",
                    //qkey
                //);

                if (qkey != 0 && Key_Event_fp) {

                    qboolean down =
                        (event.type == SDL_KEYDOWN) ? true : false;

                    //ri.Con_Printf(
                      //  PRINT_ALL,
                        //"DEBUG: chamando Key_Event_fp\n"
                    //);

                    Key_Event_fp(qkey, down);

                    //ri.Con_Printf(
                      //  PRINT_ALL,
                        //"DEBUG: Key_Event_fp terminou\n"
                    //);
                }

                break;
            }

            case SDL_MOUSEBUTTONDOWN:
            case SDL_MOUSEBUTTONUP: {
                //ri.Con_Printf(
                  //  PRINT_ALL,
                    //"DEBUG: SDL_MOUSEBUTTON\n"
                //);

                qboolean down =
                    (event.type == SDL_MOUSEBUTTONDOWN)
                    ? true
                    : false;

                // --- NOVO: Se clicou na janela, trava o mouse! ---
                if (down && !SDL_GetRelativeMouseMode()) {
                    SDL_SetRelativeMouseMode(SDL_TRUE);
                }

                if (Key_Event_fp) {

                    switch (event.button.button) {

                        case SDL_BUTTON_LEFT:
                            Key_Event_fp(K_MOUSE1, down);
                            break;

                        case SDL_BUTTON_RIGHT:
                            Key_Event_fp(K_MOUSE2, down);
                            break;

                        case SDL_BUTTON_MIDDLE:
                            Key_Event_fp(K_MOUSE3, down);
                            break;
                    }
                }

                break;
            }

            case SDL_MOUSEWHEEL:

                //ri.Con_Printf(
                  //  PRINT_ALL,
                    //"DEBUG: SDL_MOUSEWHEEL\n"
                //);

                if (Key_Event_fp) {

                    if (event.wheel.y > 0) {
                        Key_Event_fp(K_MWHEELUP, true);
                        Key_Event_fp(K_MWHEELUP, false);
                    }
                    else if (event.wheel.y < 0) {
                        Key_Event_fp(K_MWHEELDOWN, true);
                        Key_Event_fp(K_MWHEELDOWN, false);
                    }
                }

                break;
        }
    }

}

void KBD_Close(void)
{
    /* Nada específico para fechar o teclado.
       SDL é encerrada pelo SWimp_Shutdown. */
}

refexport_t GetRefAPI (refimport_t rimp)
{
    refexport_t re;

    ri = rimp;

    re.api_version = API_VERSION;

    re.BeginRegistration = R_BeginRegistration;
    re.RegisterModel = R_RegisterModel;
    re.RegisterSkin = R_RegisterModel; /* No ref_soft, skins usam o loader de modelos/pics */
    re.RegisterPic = Draw_FindPic;
    re.SetSky = R_SetSky;              /* ref_soft lida com skybox no BSP, não precisa de SetSky */
    re.EndRegistration = R_EndRegistration;

    re.RenderFrame = R_RenderFrame;

    re.DrawGetPicSize = Draw_GetPicSize;
    re.DrawPic = Draw_Pic;
    re.DrawStretchPic = Draw_StretchPic;
    re.DrawChar = Draw_Char;
    re.DrawTileClear = Draw_TileClear;
    re.DrawFill = Draw_Fill;
    re.DrawFadeScreen = Draw_FadeScreen;
    re.DrawStretchRaw = Draw_StretchRaw;

    re.Init = R_Init;
    re.Shutdown = SWimp_Shutdown;     /* <--- Aqui entra o SEU SWimp_Shutdown da SDL */

    re.CinematicSetPalette = R_CinematicSetPalette;
    re.BeginFrame = R_BeginFrame;
    re.EndFrame = SWimp_EndFrame;
    re.AppActivate = SWimp_AppActivate;

    Swap_Init ();

    return re;
}

/* -------------------------------------------------------------------------- */
/*  Mapeamento de Teclas SDL2 -> Quake II                                     */

int MapKey(SDL_Keycode key) {
    switch (key) {
        // Tecla do Console (~ / ') no Quake II usa o ASCII '`'
        case SDLK_BACKQUOTE:
		case SDLK_QUOTE:
        case 186:               // Código ABNT2 comum para ç / ~
            return '`';

        // Teclado Numérico
        case SDLK_KP_0:         return K_KP_INS;
        case SDLK_KP_1:         return K_KP_END;
        case SDLK_KP_2:         return K_KP_DOWNARROW;
        case SDLK_KP_3:         return K_KP_PGDN;
        case SDLK_KP_4:         return K_KP_LEFTARROW;
        case SDLK_KP_5:         return K_KP_5;
        case SDLK_KP_6:         return K_KP_RIGHTARROW;
        case SDLK_KP_7:         return K_KP_HOME;
        case SDLK_KP_8:         return K_KP_UPARROW;
        case SDLK_KP_9:         return K_KP_PGUP;
        case SDLK_KP_PERIOD:    return K_KP_DEL;
        case SDLK_KP_DIVIDE:    return K_KP_SLASH;
        case SDLK_KP_MULTIPLY:  return '*';
        case SDLK_KP_MINUS:     return K_KP_MINUS;
        case SDLK_KP_PLUS:      return K_KP_PLUS;
        case SDLK_KP_ENTER:     return K_KP_ENTER;

        // Teclas de Controle
        case SDLK_ESCAPE:       return K_ESCAPE;   // Retorna 27 conforme seu keys.h
        case SDLK_RETURN:       return K_ENTER;
        case SDLK_TAB:          return K_TAB;
        case SDLK_BACKSPACE:    return K_BACKSPACE;
        case SDLK_PAUSE:        return K_PAUSE;

        // Setas Direcionais
        case SDLK_UP:           return K_UPARROW;
        case SDLK_DOWN:         return K_DOWNARROW;
        case SDLK_LEFT:         return K_LEFTARROW;
        case SDLK_RIGHT:        return K_RIGHTARROW;

        // Modificadores
        case SDLK_LALT:
        case SDLK_RALT:         return K_ALT;
        case SDLK_LCTRL:
        case SDLK_RCTRL:        return K_CTRL;
        case SDLK_LSHIFT:
        case SDLK_RSHIFT:       return K_SHIFT;

        // Teclas F1-F12
        case SDLK_F1:           return K_F1;
        case SDLK_F2:           return K_F2;
        case SDLK_F3:           return K_F3;
        case SDLK_F4:           return K_F4;
        case SDLK_F5:           return K_F5;
        case SDLK_F6:           return K_F6;
        case SDLK_F7:           return K_F7;
        case SDLK_F8:           return K_F8;
        case SDLK_F9:           return K_F9;
        case SDLK_F10:          return K_F10;
        case SDLK_F11:          return K_F11;
        case SDLK_F12:          return K_F12;

        // Navegação
        case SDLK_INSERT:       return K_INS;
        case SDLK_DELETE:       return K_DEL;
        case SDLK_PAGEUP:       return K_PGUP;
        case SDLK_PAGEDOWN:     return K_PGDN;
        case SDLK_HOME:         return K_HOME;
        case SDLK_END:          return K_END;

        default:
            // Para letras, números e símbolos padrão
            if (key >= 0 && key <= 127)
                return key;
            return 0;
    }
}
extern void Cbuf_AddText (char *text);

int SWimp_Init(void *hInstance, void *wndProc)
{
    if (SDL_Init(SDL_INIT_VIDEO) < 0) {
        ri.Con_Printf(PRINT_ALL, "Erro ao inicializar SDL: %s\n", SDL_GetError());
        return 1;
    }
    RW_IN_Init();
    return 0; // Só isso!
}

qboolean SWimp_InitGraphics(qboolean windowed)
{
    ri.Con_Printf(PRINT_ALL, "--> SWimp_InitGraphics EXECUTOU!\n");
    // 1. Limpeza rigorosa de recursos antigos (Prevenção de memory leak)
    if (vid.buffer) { free(vid.buffer); vid.buffer = NULL; }
    if (texture) { SDL_DestroyTexture(texture); texture = NULL; }
    if (renderer) { SDL_DestroyRenderer(renderer); renderer = NULL; }
    if (window) { SDL_DestroyWindow(window); window = NULL; }

    // (O SDL_Init deve ficar lá no SWimp_Init, não precisa repetir aqui)

    vid_fullscreen = ri.Cvar_Get("vid_fullscreen", "0", 0);


    Uint32 flags = SDL_WINDOW_SHOWN | SDL_WINDOW_RESIZABLE;
    if (vid_fullscreen && vid_fullscreen->value) {
        flags |= SDL_WINDOW_FULLSCREEN_DESKTOP;
    }

    // 2. Criação dos subsistemas do SDL
    window = SDL_CreateWindow("Quake II", SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED, vid.width, vid.height, flags);
    if (!window) {
        ri.Con_Printf(PRINT_ALL, "Erro ao criar janela SDL: %s\n", SDL_GetError());
        return false; // Falha
    }

    renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
    if (!renderer) {
        ri.Con_Printf(PRINT_ALL, "Erro ao criar renderer SDL: %s\n", SDL_GetError());
        return false; // Falha
    }

    SDL_RenderSetLogicalSize(renderer, vid.width, vid.height);

    texture = SDL_CreateTexture(renderer, SDL_PIXELFORMAT_ARGB8888, SDL_TEXTUREACCESS_STREAMING, vid.width, vid.height);
    if (!texture) {
        ri.Con_Printf(PRINT_ALL, "Erro ao criar textura SDL: %s\n", SDL_GetError());
        return false; // Falha
    }

    // 3. Alocação vital de Memória para o Quake 2
    vid.rowbytes = vid.width;
    vid.buffer = malloc(vid.width * vid.height);


    if (!vid.buffer) {
        ri.Con_Printf(PRINT_ALL, "Erro fatal: Nao foi possivel alocar o vid.buffer!\n");
        return false;
    }

    // Zera a memória de vídeo de forma segura
    // memset(vid.buffer, 0, vid.width * vid.height);
    memset(vid.buffer, 0xAA, vid.width * vid.height);
    memset(argb_buffer, 0, vid.width * vid.height * sizeof(uint32_t));

    SWimp_InitPalette();

    // Notifica a engine que o subsistema de vídeo foi inicializado com sucesso
    ri.Cvar_Set("vid_ref", "softx");

    return true; // Sucesso!
}


void SWimp_EndFrame(void)
{
    // 1. Mantém a janela respondendo ao SO (evita congelamento no Linux)
    RW_IN_Frame();

    if (!renderer || !texture || !vid.buffer)
        return;

    int num_pixels = vid.width * vid.height;
    uint8_t *src = (uint8_t *)vid.buffer;
    uint32_t *dst = argb_buffer;

    // 2. Tradução real da paleta do Quake 2 para 32-bits (ARGB)
    for (int i = 0; i < num_pixels; i++)
    {
        uint32_t color = current_palette[src[i]];

        // Garante transparência total (Alpha = 255) para a textura do SDL
        if ((color & 0xFF000000U) == 0) {
            color |= 0xFF000000U;
        }

        dst[i] = color;
    }

    // 3. Atualiza a textura no hardware e apresenta o frame
    SDL_UpdateTexture(texture, NULL, argb_buffer, vid.width * sizeof(uint32_t));
    SDL_RenderClear(renderer);
    SDL_RenderCopy(renderer, texture, NULL, NULL);
    SDL_RenderPresent(renderer);
}

/* -------------------------------------------------------------------------- */
/*  Estrutura de modos de vídeo padrão do Quake II                             */
/* -------------------------------------------------------------------------- */
typedef struct {
    int width;
    int height;
} vmode_t;

static vmode_t modelist[] = {
    { 320, 240 },
    { 400, 300 },
    { 512, 384 },
    { 640, 480 },
    { 800, 600 },
    { 960, 720 },
    { 1024, 768 },
    { 1152, 864 },
    { 1280, 960 },
    { 1600, 1200 },
	// --- SUAS NOVAS RESOLUÇÕES AQUI ---
    { 1280, 720 },  // 720p
    { 1366, 768 },  // HD Notebook
    { 1920, 1080 }  // 1080p Full HD
};

#define NUM_MODES (sizeof(modelist) / sizeof(modelist[0]))

/* -------------------------------------------------------------------------- */
/*  Definição e Troca do Modo de Vídeo (SWimp_SetMode)                        */
/* -------------------------------------------------------------------------- */
rserr_t SWimp_SetMode(int *pwidth, int *pheight, int mode, qboolean fullscreen)
{
    if (mode < 0 || mode >= NUM_MODES) {
        return rserr_invalid_mode;
    }

    vid.width  = modelist[mode].width;
    vid.height = modelist[mode].height;
    vid.rowbytes = vid.width;

	viddef.width = vid.width;
    viddef.height = vid.height;

    if (pwidth)  *pwidth  = vid.width;
    if (pheight) *pheight = vid.height;

    //ri.Con_Printf(PRINT_ALL, "DEBUG: SetMode -> %dx%d\n", vid.width, vid.height);

    // 3. Inicializa os gráficos e aloca os buffers com a nova resolução
    if (!SWimp_InitGraphics(!fullscreen)) {
        ri.Con_Printf(PRINT_ALL, "DEBUG: SWimp_SetMode FALHOU no InitGraphics\n");
        return rserr_invalid_mode;
    }

    if (!vid.buffer) {
        ri.Con_Printf(PRINT_ALL, "DEBUG: SWimp_SetMode FALHOU (vid.buffer == NULL)\n");
        return rserr_invalid_mode;
    }

    R_GammaCorrectAndSetPalette((const unsigned char *)d_8to24table);

    return rserr_ok;
}

void App_GrabMouse(qboolean grab){
    if(grab){
        SDL_SetRelativeMouseMode(SDL_TRUE);
    }else{
        SDL_SetRelativeMouseMode(SDL_FALSE);
    }
}

void SWimp_InitPalette(void)
{
    for (int i = 0; i < 256; i++) {
        // Cria uma paleta em escala de cinza/colorida inicial com Alpha 255
        current_palette[i] = (0xFF000000U) | ((uint32_t)i << 16) | ((uint32_t)i << 8) | (uint32_t)i;
    }
}
/* -------------------------------------------------------------------------- */
/*  Atualização de Paleta de Cores (SWimp_SetPalette)                          */
/* -------------------------------------------------------------------------- */
void SWimp_SetPalette(const unsigned char *palette)
{
    if (!palette) return;

    // A tabela d_8to24table enviada pelo ref_soft é um array de 256 uint32_t
    const uint32_t *pal32 = (const uint32_t *)palette;

    for (int i = 0; i < 256; i++)
    {
        uint32_t c = pal32[i];

        // No ref_soft, a tabela vem gravada em formato 0x00BBGGRR ou 0x00RRGGBB
        uint8_t r = (c >> 0)  & 0xFF;
        uint8_t g = (c >> 8)  & 0xFF;
        uint8_t b = (c >> 16) & 0xFF;

        // Converte para o ARGB8888 do SDL (Alpha = 255)
        current_palette[i] = (0xFF000000U) | (r << 16) | (g << 8) | b;
    }
}

/* Retorna se a aplicação possui foco de entrada */
qboolean SWimp_AppActive(void) {
    if (!window) return false;
    Uint32 flags = SDL_GetWindowFlags(window);
    return (flags & SDL_WINDOW_INPUT_FOCUS) ? true : false;
}

void SWimp_AppActivate(qboolean active){
    if(active){
        App_GrabMouse(true);
    }else{
        App_GrabMouse(false);
    }
}

void SWimp_Shutdown(void) {
    App_GrabMouse(false);

    if (texture) {
        SDL_DestroyTexture(texture);
        texture = NULL;
    }
    if (renderer) {
        SDL_DestroyRenderer(renderer);
        renderer = NULL;
    }
    if (window) {
        SDL_DestroyWindow(window);
        window = NULL;
    }

    SDL_QuitSubSystem(SDL_INIT_VIDEO);
}
