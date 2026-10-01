# 모델 설치 폴더

## 사용법

**폴더 하나 = 모델 하나**입니다. 폴더를 만들고 파일을 넣기만 하면 됩니다.

```
models/
├── MyLlm/                    ← LLM (선택, 없어도 됨)
│   └── model.gguf
│
├── MyImageModel/             ← 이미지 모델
│   ├── model.safetensors
│   └── style_lora.safetensors    ← LoRA (선택)
│
└── flux1-dev/                ← Diffusers 형식은 폴더째 복사
    ├── model_index.json
    ├── transformer/
    ├── vae/
    └── text_encoder/
```

## 알아서 인식되는 것들

폴더 이름이나 파일 이름은 상관없습니다. 프로그램이 파일 내용을 열어
무엇인지 확인합니다.

- `.safetensors` / `.ckpt` → U-Net·VAE·텍스트 인코더·LoRA 자동 분류
- `model_index.json` 있는 폴더 → Diffusers 모델로 인식
- `.gguf` → LLM으로 인식

그래서 `sd15_base.safetensors` 처럼 이름을 바꿔도 SD1.5로 정확히 인식합니다.

## 서브폴더는 선택 사항

정돈용으로 아래처럼 쓸 수 있습니다. **없어도 똑같이 동작합니다.**

| 폴더 | 넣는 것 | 없어도? |
|---|---|---|
| `vae/` | 커스텀 VAE | 내장 VAE 사용 |
| `lora/` | LoRA | LoRA 미사용 |
| `text_encoder/` | CLIP 등 | 내장 인코더 사용 |

## 삭제와 추가

- **추가**: 새 폴더 만들고 파일 넣기 → `모델 새로고침` 클릭
- **삭제**: 폴더째 삭제 → `모델 새로고침` 클릭

`outputs/`, `sessions/` 처럼 프로그램이 알아서 쓰기 때문에
수동 정리할 필요는 없습니다.

## 인식되지 않을 때

프로그램이 아키텍처를 모르면 `unknown`으로 표시합니다.
`config/user_models.json`에 직접 지정할 수 있습니다.

```json
{
  "your_model.safetensors": {
    "kind": "image",
    "architecture": "sd15",
    "prompt_style": "tag"
  }
}
```