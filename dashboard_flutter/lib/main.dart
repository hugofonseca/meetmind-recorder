import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;
import 'package:printing/printing.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

void main() {
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'XLR8 de Reuniões',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF01696f),
          brightness: Brightness.light,
        ),
        useMaterial3: true,
        fontFamily: 'Roboto',
      ),
      home: const DashboardPage(),
    );
  }
}

class DashboardPage extends StatefulWidget {
  const DashboardPage({super.key});

  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends State<DashboardPage> {
  final TextEditingController _transcricaoCtrl = TextEditingController();
  final TextEditingController _ataCtrl = TextEditingController();

  final String _baseUrl = 'http://localhost:5000';

  String _tipo = '';
  String _ataOriginal = '';
  String? _selectedMeetingId;

  bool _carregando = false;
  bool _carregandoLista = false;
  bool _carregandoDetalhe = false;
  bool _ataEditada = false;
  bool _modoEdicao = false;
  bool _modoManual = false;

  List<dynamic> _meetings = [];

  static const Color _primary = Color(0xFF01696f);
  static const Color _primaryDark = Color(0xFF0c4e54);
  static const Color _bgPage = Color(0xFFf7f6f2);
  static const Color _bgCard = Color(0xFFffffff);
  static const Color _bgHeader = Color(0xFF0f172a);
  static const Color _textMuted = Color(0xFF7a7974);
  static const Color _border = Color(0xFFdcd9d5);
  static const Color _warningBg = Color(0xFFfef9ec);
  static const Color _warningBorder = Color(0xFFf6d860);
  static const Color _warningText = Color(0xFF92710a);

  Map<String, Color> get _tipoCores => {
        'PLANEJAMENTO': const Color(0xFF0d7377),
        'DECISAO': const Color(0xFF7a39bb),
        'RETROSPECTIVA': const Color(0xFF437a22),
        'STATUS': const Color(0xFF006494),
        'BRAINSTORMING': const Color(0xFFda7101),
      };

  @override
  void initState() {
    super.initState();
    _carregarMeetings();
  }

  Future<void> _carregarMeetings() async {
    setState(() => _carregandoLista = true);

    try {
      final resp = await http.get(Uri.parse('$_baseUrl/meetings'));

      if (resp.statusCode == 200) {
        final dados = jsonDecode(resp.body) as List<dynamic>;
        setState(() {
          _meetings = dados;
        });
      } else {
        _mostrarSnackbar('Erro ao carregar reuniões: ${resp.statusCode}', isError: true);
      }
    } catch (e) {
      _mostrarSnackbar('Falha ao carregar reuniões: $e', isError: true);
    } finally {
      setState(() => _carregandoLista = false);
    }
  }

  Future<void> _abrirMeeting(String id) async {
    setState(() {
      _carregandoDetalhe = true;
      _modoManual = false;
      _modoEdicao = false;
      _ataEditada = false;
      _selectedMeetingId = id;
    });

    try {
      final resp = await http.get(Uri.parse('$_baseUrl/meetings/$id'));

      if (resp.statusCode == 200) {
        final dados = jsonDecode(resp.body);

        setState(() {
          _tipo = (dados['tipo'] ?? '').toString().toUpperCase();
          _ataOriginal = (dados['ata'] ?? '').toString();
          _ataCtrl.text = _ataOriginal;
          _transcricaoCtrl.text = (dados['transcript_txt'] ?? dados['resumo_consolidado'] ?? '').toString();
        });
      } else {
        _mostrarSnackbar('Erro ao abrir reunião: ${resp.statusCode}', isError: true);
      }
    } catch (e) {
      _mostrarSnackbar('Falha ao abrir reunião: $e', isError: true);
    } finally {
      setState(() => _carregandoDetalhe = false);
    }
  }

  void _novaAtaManual() {
    setState(() {
      _modoManual = true;
      _selectedMeetingId = null;
      _tipo = '';
      _ataOriginal = '';
      _ataCtrl.clear();
      _transcricaoCtrl.clear();
      _ataEditada = false;
      _modoEdicao = false;
    });
  }

  Future<void> _gerarAtaManual() async {
    if (_transcricaoCtrl.text.trim().isEmpty) {
      _mostrarSnackbar('Cole a transcrição antes de gerar a ata.', isError: true);
      return;
    }

    setState(() {
      _carregando = true;
      _ataEditada = false;
      _modoEdicao = false;
    });

    try {
      final resp = await http.post(
        Uri.parse('$_baseUrl/gerar-ata'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'transcript': _transcricaoCtrl.text}),
      );

      if (resp.statusCode == 200) {
        final dados = jsonDecode(resp.body);

        setState(() {
          _tipo = (dados['tipo'] ?? '').toString().toUpperCase();
          _ataOriginal = (dados['ata'] ?? '').toString();
          _ataCtrl.text = _ataOriginal;
        });

        _mostrarSnackbar('Ata gerada com sucesso.');
        await _carregarMeetings();
      } else {
        _mostrarSnackbar('Erro ${resp.statusCode}', isError: true);
      }
    } catch (e) {
      _mostrarSnackbar('Falha ao chamar API: $e', isError: true);
    } finally {
      setState(() => _carregando = false);
    }
  }

  Future<void> _exportarPdf() async {
    if (_ataCtrl.text.trim().isEmpty) {
      _mostrarSnackbar('Nenhuma ata para exportar.', isError: true);
      return;
    }

    final doc = pw.Document();
    final boldFont = await PdfGoogleFonts.notoSansBold();
    final regularFont = await PdfGoogleFonts.notoSansRegular();
    final linhas = _ataCtrl.text.split('\n');

    doc.addPage(
      pw.MultiPage(
        pageFormat: PdfPageFormat.a4,
        margin: const pw.EdgeInsets.all(40),
        build: (ctx) {
          final widgets = <pw.Widget>[];

          widgets.add(
            pw.Container(
              padding: const pw.EdgeInsets.only(bottom: 16),
              decoration: const pw.BoxDecoration(
                border: pw.Border(bottom: pw.BorderSide(color: PdfColors.grey300, width: 1)),
              ),
              child: pw.Column(
                crossAxisAlignment: pw.CrossAxisAlignment.start,
                children: [
                  pw.Text(
                    'ATA DE REUNIÃO',
                    style: pw.TextStyle(
                      font: boldFont,
                      fontSize: 20,
                      color: PdfColor.fromHex('01696f'),
                    ),
                  ),
                  if (_tipo.isNotEmpty)
                    pw.Container(
                      margin: const pw.EdgeInsets.only(top: 4),
                      padding: const pw.EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                      decoration: pw.BoxDecoration(
                        color: PdfColor.fromHex('cedcd8'),
                        borderRadius: pw.BorderRadius.circular(4),
                      ),
                      child: pw.Text(
                        _tipo,
                        style: pw.TextStyle(
                          font: boldFont,
                          fontSize: 10,
                          color: PdfColor.fromHex('01696f'),
                        ),
                      ),
                    ),
                ],
              ),
            ),
          );

          widgets.add(pw.SizedBox(height: 16));

          for (final linha in linhas) {
            if (linha.trim().isEmpty) {
              widgets.add(pw.SizedBox(height: 8));
              continue;
            }

            if (linha.trim().startsWith('**') && linha.trim().endsWith('**')) {
              final textoLimpo = linha.trim().replaceAll('**', '');
              widgets.add(
                pw.Padding(
                  padding: const pw.EdgeInsets.only(top: 10, bottom: 4),
                  child: pw.Text(
                    textoLimpo,
                    style: pw.TextStyle(font: boldFont, fontSize: 13),
                  ),
                ),
              );
              continue;
            }

            final isItem = RegExp(r'^\d+\.\s|\*\s|-\s').hasMatch(linha.trim());
            final spans = _parseBoldSpans(linha, regularFont, boldFont);

            widgets.add(
              pw.Padding(
                padding: pw.EdgeInsets.only(left: isItem ? 12 : 0, bottom: 3),
                child: pw.RichText(text: pw.TextSpan(children: spans)),
              ),
            );
          }

          return widgets;
        },
      ),
    );

    await Printing.layoutPdf(onLayout: (format) async => doc.save());
  }

  List<pw.InlineSpan> _parseBoldSpans(String text, pw.Font regular, pw.Font bold) {
    final spans = <pw.InlineSpan>[];
    final regex = RegExp(r'\*\*(.+?)\*\*');
    int lastEnd = 0;

    for (final match in regex.allMatches(text)) {
      if (match.start > lastEnd) {
        spans.add(
          pw.TextSpan(
            text: text.substring(lastEnd, match.start),
            style: pw.TextStyle(font: regular, fontSize: 11),
          ),
        );
      }

      spans.add(
        pw.TextSpan(
          text: match.group(1),
          style: pw.TextStyle(font: bold, fontSize: 11),
        ),
      );

      lastEnd = match.end;
    }

    if (lastEnd < text.length) {
      spans.add(
        pw.TextSpan(
          text: text.substring(lastEnd),
          style: pw.TextStyle(font: regular, fontSize: 11),
        ),
      );
    }

    if (spans.isEmpty) {
      return [pw.TextSpan(text: text, style: pw.TextStyle(font: regular, fontSize: 11))];
    }

    return spans;
  }

  void _mostrarSnackbar(String msg, {bool isError = false}) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(msg),
        backgroundColor: isError ? Colors.red[700] : _primary,
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      ),
    );
  }

  Color _corDoTipo(String tipo) => _tipoCores[tipo] ?? _primary;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bgPage,
      appBar: AppBar(
        backgroundColor: _bgHeader,
        foregroundColor: Colors.white,
        elevation: 0,
        title: Row(
          children: [
            Container(
              width: 28,
              height: 28,
              margin: const EdgeInsets.only(right: 10),
              decoration: BoxDecoration(
                color: _primary,
                borderRadius: BorderRadius.circular(6),
              ),
              child: const Icon(Icons.notes_rounded, color: Colors.white, size: 16),
            ),
            const Text(
              'XLR8 de Reuniões',
              style: TextStyle(fontWeight: FontWeight.w600, fontSize: 16),
            ),
            const SizedBox(width: 6),
            Text(
              '— Dashboard de Atas',
              style: TextStyle(
                fontWeight: FontWeight.w300,
                fontSize: 15,
                color: Colors.white.withOpacity(0.55),
              ),
            ),
          ],
        ),
        actions: [
          TextButton.icon(
            onPressed: _carregarMeetings,
            icon: const Icon(Icons.refresh_rounded, color: Colors.white, size: 18),
            label: const Text('Atualizar', style: TextStyle(color: Colors.white)),
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(20),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 340,
              child: _Painel(
                titulo: 'Reuniões salvas',
                icone: Icons.folder_copy_rounded,
                acaoWidget: TextButton.icon(
                  onPressed: _novaAtaManual,
                  icon: const Icon(Icons.add_rounded, size: 14),
                  label: const Text('Manual', style: TextStyle(fontSize: 13)),
                  style: TextButton.styleFrom(foregroundColor: _primary),
                ),
                child: Column(
                  children: [
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(12),
                      margin: const EdgeInsets.only(bottom: 12),
                      decoration: BoxDecoration(
                        color: const Color(0xFFfafaf8),
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: _border),
                      ),
                      child: Text(
                        _modoManual
                            ? 'Modo manual ativo: cole uma transcrição no painel central.'
                            : 'Selecione uma reunião gravada no Discord para abrir a ata.',
                        style: const TextStyle(
                          fontSize: 12.5,
                          color: Color(0xFF5c5a55),
                          height: 1.5,
                        ),
                      ),
                    ),
                    Expanded(
                      child: _carregandoLista
                          ? const Center(child: CircularProgressIndicator())
                          : _meetings.isEmpty
                              ? const _ListaVazia()
                              : ListView.separated(
                                  itemCount: _meetings.length,
                                  separatorBuilder: (_, __) => const SizedBox(height: 10),
                                  itemBuilder: (context, index) {
                                    final item = _meetings[index];
                                    final id = (item['id'] ?? '').toString();
                                    final tipo = (item['tipo'] ?? '').toString().toUpperCase();
                                    final preview = (item['preview'] ?? '').toString();
                                    final ativo = _selectedMeetingId == id && !_modoManual;

                                    return InkWell(
                                      onTap: () => _abrirMeeting(id),
                                      borderRadius: BorderRadius.circular(10),
                                      child: Container(
                                        padding: const EdgeInsets.all(12),
                                        decoration: BoxDecoration(
                                          color: ativo ? _primary.withOpacity(0.08) : Colors.white,
                                          borderRadius: BorderRadius.circular(10),
                                          border: Border.all(
                                            color: ativo ? _primary : _border,
                                          ),
                                        ),
                                        child: Column(
                                          crossAxisAlignment: CrossAxisAlignment.start,
                                          children: [
                                            Row(
                                              children: [
                                                Expanded(
                                                  child: Text(
                                                    id,
                                                    maxLines: 1,
                                                    overflow: TextOverflow.ellipsis,
                                                    style: const TextStyle(
                                                      fontSize: 12.5,
                                                      fontWeight: FontWeight.w700,
                                                      color: Color(0xFF28251d),
                                                    ),
                                                  ),
                                                ),
                                              ],
                                            ),
                                            const SizedBox(height: 8),
                                            if (tipo.isNotEmpty)
                                              Container(
                                                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                                                decoration: BoxDecoration(
                                                  color: _corDoTipo(tipo).withOpacity(0.12),
                                                  borderRadius: BorderRadius.circular(20),
                                                  border: Border.all(
                                                    color: _corDoTipo(tipo).withOpacity(0.25),
                                                  ),
                                                ),
                                                child: Text(
                                                  tipo,
                                                  style: TextStyle(
                                                    fontSize: 10.5,
                                                    fontWeight: FontWeight.w700,
                                                    color: _corDoTipo(tipo),
                                                    letterSpacing: 0.4,
                                                  ),
                                                ),
                                              ),
                                            const SizedBox(height: 8),
                                            Text(
                                              preview.isEmpty ? 'Sem preview disponível.' : preview,
                                              maxLines: 4,
                                              overflow: TextOverflow.ellipsis,
                                              style: const TextStyle(
                                                fontSize: 12.5,
                                                color: Color(0xFF5c5a55),
                                                height: 1.5,
                                              ),
                                            ),
                                          ],
                                        ),
                                      ),
                                    );
                                  },
                                ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: _Painel(
                titulo: _modoManual ? 'Transcrição manual' : 'Transcrição / Resumo',
                icone: Icons.mic_rounded,
                acaoWidget: _modoManual && _transcricaoCtrl.text.isNotEmpty
                    ? TextButton.icon(
                        onPressed: () {
                          setState(() {
                            _transcricaoCtrl.clear();
                          });
                        },
                        icon: const Icon(Icons.clear, size: 14),
                        label: const Text('Limpar', style: TextStyle(fontSize: 13)),
                        style: TextButton.styleFrom(foregroundColor: _textMuted),
                      )
                    : null,
                child: Column(
                  children: [
                    Expanded(
                      child: _carregandoDetalhe
                          ? const Center(child: CircularProgressIndicator())
                          : TextField(
                              controller: _transcricaoCtrl,
                              maxLines: null,
                              expands: true,
                              readOnly: !_modoManual,
                              style: const TextStyle(
                                fontSize: 13.5,
                                height: 1.6,
                                color: Color(0xFF28251d),
                              ),
                              decoration: InputDecoration(
                                hintText: _modoManual
                                    ? 'Cole aqui a transcrição...'
                                    : 'Selecione uma reunião salva à esquerda.',
                                hintStyle: TextStyle(
                                  color: _textMuted.withOpacity(0.7),
                                  fontSize: 13.5,
                                ),
                                border: OutlineInputBorder(
                                  borderRadius: BorderRadius.circular(8),
                                  borderSide: const BorderSide(color: _border),
                                ),
                                enabledBorder: OutlineInputBorder(
                                  borderRadius: BorderRadius.circular(8),
                                  borderSide: const BorderSide(color: _border),
                                ),
                                focusedBorder: OutlineInputBorder(
                                  borderRadius: BorderRadius.circular(8),
                                  borderSide: const BorderSide(color: _primary, width: 1.5),
                                ),
                                filled: true,
                                fillColor: const Color(0xFFfafaf8),
                                contentPadding: const EdgeInsets.all(14),
                              ),
                            ),
                    ),
                    const SizedBox(height: 12),
                    SizedBox(
                      width: double.infinity,
                      height: 46,
                      child: ElevatedButton.icon(
                        onPressed: (!_modoManual || _carregando) ? null : _gerarAtaManual,
                        icon: _carregando
                            ? const SizedBox(
                                width: 16,
                                height: 16,
                                child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                              )
                            : const Icon(Icons.auto_awesome_rounded, size: 18),
                        label: Text(
                          _carregando ? 'Gerando ata...' : 'Gerar ata com IA',
                          style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14),
                        ),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: _primary,
                          foregroundColor: Colors.white,
                          disabledBackgroundColor: _primary.withOpacity(0.45),
                          elevation: 0,
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: _Painel(
                titulo: 'Ata gerada',
                icone: Icons.description_rounded,
                badgeWidget: _tipo.isNotEmpty
                    ? Container(
                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
                        decoration: BoxDecoration(
                          color: _corDoTipo(_tipo).withOpacity(0.12),
                          borderRadius: BorderRadius.circular(20),
                          border: Border.all(color: _corDoTipo(_tipo).withOpacity(0.3)),
                        ),
                        child: Text(
                          _tipo,
                          style: TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w700,
                            color: _corDoTipo(_tipo),
                            letterSpacing: 0.5,
                          ),
                        ),
                      )
                    : null,
                acaoWidget: _ataCtrl.text.isNotEmpty
                    ? TextButton.icon(
                        onPressed: () => setState(() => _modoEdicao = !_modoEdicao),
                        icon: Icon(_modoEdicao ? Icons.visibility_rounded : Icons.edit_rounded, size: 14),
                        label: Text(
                          _modoEdicao ? 'Visualizar' : 'Editar',
                          style: const TextStyle(fontSize: 13),
                        ),
                        style: TextButton.styleFrom(foregroundColor: _primary),
                      )
                    : null,
                child: Column(
                  children: [
                    if (_ataEditada)
                      Container(
                        width: double.infinity,
                        margin: const EdgeInsets.only(bottom: 10),
                        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                        decoration: BoxDecoration(
                          color: _warningBg,
                          borderRadius: BorderRadius.circular(6),
                          border: Border.all(color: _warningBorder),
                        ),
                        child: Row(
                          children: [
                            const Icon(Icons.edit_note_rounded, size: 16, color: _warningText),
                            const SizedBox(width: 8),
                            const Expanded(
                              child: Text(
                                'Ata editada manualmente',
                                style: TextStyle(
                                  fontSize: 12.5,
                                  color: _warningText,
                                  fontWeight: FontWeight.w500,
                                ),
                              ),
                            ),
                            TextButton(
                              onPressed: () => setState(() {
                                _ataCtrl.text = _ataOriginal;
                                _ataEditada = false;
                              }),
                              style: TextButton.styleFrom(
                                foregroundColor: _warningText,
                                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 0),
                                minimumSize: Size.zero,
                                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                              ),
                              child: const Text('Restaurar original', style: TextStyle(fontSize: 12)),
                            ),
                          ],
                        ),
                      ),
                    Expanded(
                      child: _ataCtrl.text.trim().isEmpty
                          ? const _EmptyState()
                          : _modoEdicao
                              ? TextField(
                                  controller: _ataCtrl,
                                  maxLines: null,
                                  expands: true,
                                  onChanged: (v) {
                                    setState(() {
                                      _ataEditada = v != _ataOriginal;
                                    });
                                  },
                                  style: const TextStyle(
                                    fontSize: 13.5,
                                    height: 1.6,
                                    color: Color(0xFF28251d),
                                  ),
                                  decoration: InputDecoration(
                                    border: OutlineInputBorder(
                                      borderRadius: BorderRadius.circular(8),
                                      borderSide: const BorderSide(color: _primary, width: 1.5),
                                    ),
                                    focusedBorder: OutlineInputBorder(
                                      borderRadius: BorderRadius.circular(8),
                                      borderSide: const BorderSide(color: _primary, width: 1.5),
                                    ),
                                    enabledBorder: OutlineInputBorder(
                                      borderRadius: BorderRadius.circular(8),
                                      borderSide: const BorderSide(color: _primary, width: 1.5),
                                    ),
                                    filled: true,
                                    fillColor: const Color(0xFFfafaf8),
                                    contentPadding: const EdgeInsets.all(14),
                                  ),
                                )
                              : Container(
                                  decoration: BoxDecoration(
                                    color: _bgCard,
                                    borderRadius: BorderRadius.circular(8),
                                    border: Border.all(color: _border),
                                  ),
                                  child: Markdown(
                                    controller: ScrollController(),
                                    data: _ataCtrl.text,
                                    padding: const EdgeInsets.all(16),
                                    styleSheet: MarkdownStyleSheet(
                                      p: const TextStyle(
                                        fontSize: 13.5,
                                        height: 1.7,
                                        color: Color(0xFF28251d),
                                      ),
                                      strong: const TextStyle(
                                        fontWeight: FontWeight.w700,
                                        color: Color(0xFF0f172a),
                                      ),
                                      h1: const TextStyle(
                                        fontSize: 17,
                                        fontWeight: FontWeight.w700,
                                        color: Color(0xFF0f172a),
                                      ),
                                      h2: const TextStyle(
                                        fontSize: 15,
                                        fontWeight: FontWeight.w700,
                                        color: Color(0xFF0f172a),
                                      ),
                                      h3: const TextStyle(
                                        fontSize: 14,
                                        fontWeight: FontWeight.w600,
                                        color: Color(0xFF0f172a),
                                      ),
                                      listBullet: const TextStyle(
                                        fontSize: 13.5,
                                        color: Color(0xFF28251d),
                                      ),
                                      blockquoteDecoration: BoxDecoration(
                                        color: const Color(0xFFf0f7f7),
                                        borderRadius: BorderRadius.circular(4),
                                        border: const Border(
                                          left: BorderSide(color: _primary, width: 3),
                                        ),
                                      ),
                                    ),
                                  ),
                                ),
                    ),
                    const SizedBox(height: 12),
                    SizedBox(
                      width: double.infinity,
                      height: 46,
                      child: ElevatedButton.icon(
                        onPressed: _ataCtrl.text.trim().isEmpty ? null : _exportarPdf,
                        icon: const Icon(Icons.picture_as_pdf_rounded, size: 18),
                        label: const Text(
                          'Exportar como PDF',
                          style: TextStyle(fontWeight: FontWeight.w600, fontSize: 14),
                        ),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: _bgHeader,
                          foregroundColor: Colors.white,
                          disabledBackgroundColor: Colors.grey,
                          elevation: 0,
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Painel extends StatelessWidget {
  final String titulo;
  final IconData icone;
  final Widget child;
  final Widget? badgeWidget;
  final Widget? acaoWidget;

  const _Painel({
    required this.titulo,
    required this.icone,
    required this.child,
    this.badgeWidget,
    this.acaoWidget,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFdcd9d5)),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.04),
            blurRadius: 12,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            decoration: const BoxDecoration(
              border: Border(bottom: BorderSide(color: Color(0xFFdcd9d5))),
            ),
            child: Row(
              children: [
                Icon(icone, size: 16, color: const Color(0xFF01696f)),
                const SizedBox(width: 8),
                Text(
                  titulo,
                  style: const TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                    color: Color(0xFF28251d),
                  ),
                ),
                if (badgeWidget != null) ...[
                  const SizedBox(width: 8),
                  badgeWidget!,
                ],
                const Spacer(),
                if (acaoWidget != null) acaoWidget!,
              ],
            ),
          ),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: child,
            ),
          ),
        ],
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.notes_rounded, size: 48, color: Colors.grey[300]),
          const SizedBox(height: 12),
          Text(
            'Nenhuma ata carregada',
            style: TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w600,
              color: Colors.grey[500],
            ),
          ),
          const SizedBox(height: 6),
          Text(
            'Selecione uma reunião salva ou use o modo manual.',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 13, color: Colors.grey[400]),
          ),
        ],
      ),
    );
  }
}

class _ListaVazia extends StatelessWidget {
  const _ListaVazia();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Text(
        'Nenhuma reunião salva encontrada.',
        style: TextStyle(
          fontSize: 13,
          color: Colors.grey[500],
        ),
      ),
    );
  }
}