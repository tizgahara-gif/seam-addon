# Auto Seam UV Equalizer v0.7.x

Blender 5.1向けに、ZBrush / GoZから来たメッシュのシーム作成、UV展開、配置、対称転送、検証を段階的に行うアドオンです。新しいサイドバーは複合的な Quick Actions ではなく、現在の工程と作用範囲が分かる5つのセクションで構成されています。

## Installation

`auto_seam_uv_equalizer.zip` を **Edit > Preferences > Add-ons > Install...** からインストールし、3D Viewの **N > Auto UV** を開きます。GitHubのソースアーカイブではなく、リリース用zipを使用してください。

## Five-stage panel

### 1. Seam

**Classic** は角度、マテリアル境界、開放境界、非多様体の規則でシームを生成します。**Chart-Based** は Organic / Cloth、Hard Surface、Cylinder / Strip、Manual Assisted のプリセットとUV品質評価を使います。Analyze Seamsは診断のみ、Generate Seamsは適用です。

Analyze / Generateの作用範囲は選択メッシュオブジェクトです。Selected BoundaryとMirror Seamなどの **Assist — Active Object** はアクティブオブジェクトだけに作用します。Force、Protect、Clear TagsおよびProfessional Garment PriorはChart-Based専用です。詳細パラメータとCharacter Front AxisはAdvanced内にあります。

### 2. Unwrap

**Unwrap Selected Faces** はEdit Modeの選択面だけを変更します。**Unwrap Selected Objects** は選択メッシュオブジェクト全体を既存シームで展開します。**Unwrap Margin** はこのUV展開だけに使用され、Pack Marginとは独立しています。UVがなくCreate UV If Missingが有効な場合は、UV展開時に新規作成します。Ring / StripではSeam、Layout、Spacing、Orientation、Normalizeを設定し、検出と展開を個別に実行できます。

### 3. Layout

**Weighted Island Layout** はScope、Target UV Region（FULL / LEFT_HALF / RIGHT_HALF）、Density Influence、Scale Mode、Texture Size、Padding Pixelsを使用します。

**Pack Islands** は別工程で、Pack Margin、Rotation、Margin Methodを使用し、選択した各オブジェクトを個別にパックします。複数オブジェクトを一つの0–1共有領域へ置く場合は **Atlas Pack Selected Objects** を使用します。折りたたみ式Atlas SettingsからUV Source、Texture Size、Pixel Margin、Average Island Scale、Allow Rotationを設定できます。Atlas Packはオブジェクトを結合せず、テクスチャ画像やマテリアルも統合しません。

### 4. Symmetry

**Mesh Symmetry Axis** はProfessional Garment Prior、Mirror Seam、Validate Symmetry、Standard UV Transfer、Exact Texture-Xのジオメトリ対応付けで共通です。Direction / Source Sideは用途別のままです。ScopeがSelected Facesの場合はEdit Modeが必須で、Object Modeでは3つの対称処理ボタンが無効になります。Standard UV TransferはOverlapまたはSeparate Mirrored（Island Gap付き）を選択できます。

Exact Texture-Xの **Texture Source Side** は3D Mesh Source Sideとは独立しています。転送元UVは指定したLeft HalfまたはRight Halfと0–1領域内に完全に収まる必要があります。Weighted TargetとTexture Sourceが一致しない場合、パネルが実行前に警告します。「Layout settings match Exact Texture-X.」は設定値の一致だけを示し、UVや対称対応の検証成功を保証しません。本当の検証はOperator実行時に行います。

### 5. Validation

**Check Overlap** は問題面を非破壊的に選択し、マテリアルを変更しません。結果選択はEdit Modeへ戻った後も残ります。**Clear Overlap Selection** で解除します。**Check Stretch** の結果はLast Stretch Reportに表示します。

## Recommended workflow

```text
ZBrush
↓
GoZ
↓
Seam
↓
Unwrap
↓
Weighted Layout / Pack
↓
Symmetry
↓
Validation
↓
External Texture Paint
```

通常はChart-Based + Organic / ClothからGenerate Seams、Unwrap Selected Objects、Weighted FULL、Pack、Validationへ進みます。

Exact Texture-Xを使う場合は次の順序にします。

```text
Weighted LEFT_HALF または RIGHT_HALF
↓
Exact Texture-X（同じTexture Source Side）
```

**この2工程の間やExact Texture-X後にPackを実行しないでください。** Packは厳密な `U_source + U_destination = 1` の関係を壊す可能性があります。

## Compatibility

旧 **Auto Seam + Unwrap** と **Auto Unwrap + Pack** operator IDは`.blend`やスクリプト互換用backendとして残りますが、通常パネルには表示されません。アルゴリズム（Classic、Chart-Based、Professional Prior、Ring / Strip、Weighted BBox packing、Symmetry pairing、Exact Texture-X、Overlap detection）は変更していません。

## Known limitations

- Chart-Based候補は実測UV品質に基づくため、意図した見えない位置を常に選ぶとは限りません。
- Ring / Stripは対応する連結quad topologyが必要です。
- Exact Texture-Xは事前に片側halfへ収まったUVを必要とします。
- Atlas Packはmaterial統合、texture bake、画像統合を行いません。
- 非一様Object Scaleや複雑なhero assetは手動確認が必要です。
