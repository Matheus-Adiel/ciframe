angular.module('deciframeApp').controller('SequenciaController', function($http, $window, ngProgressFactory, $anchorScroll, $location, GENEROS) {
  var COR_FALLBACK = '#2E1C74';
  var CORES = {
    'C':  '#e6b300', 'C#': '#e6b300', 'Db': '#e6b300',
    'D':  '#cb6018', 'D#': '#cb6018', 'Eb': '#cb6018',
    'E':  '#b72c52',
    'F':  '#ba007c', 'F#': '#ba007c', 'Gb': '#ba007c',
    'G':  '#7b057e', 'G#': '#7b057e', 'Ab': '#7b057e',
    'A':  '#76aadb', 'A#': '#76aadb', 'Bb': '#76aadb',
    'B':  '#a3bd31'
  };
  var SUGESTOES = [
    'C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B',
    'Cm', 'C#m', 'Dm', 'D#m', 'Em', 'Fm', 'F#m', 'Gm', 'G#m', 'Am',
    'A#m', 'Bm', 'C7', 'D7', 'E7', 'F7', 'G7', 'A7', 'B7'
  ];

  var corDoAcorde = function(acorde) {
    var match = /^([A-Ga-g])([#b]?)/.exec(acorde || '');
    if (!match) {
      return COR_FALLBACK;
    }
    var raiz = match[1].toUpperCase() + match[2];
    return CORES[raiz] || COR_FALLBACK;
  };

  var adaptarAcorde = function(acorde) {
    return { 'acorde': acorde, 'cor': corDoAcorde(acorde) };
  };

  var adaptarSequencia = function(sequencia) {
    return {
      'id': sequencia.id,
      'origem': sequencia.origem,
      'criado_em': sequencia.criado_em,
      'acordes': (sequencia.acordes || []).map(adaptarAcorde)
    };
  };

  var vm = this;
  vm.sequencias = [];
  vm.sugestoes = SUGESTOES.map(adaptarAcorde);
  vm.novaSequencia = '';
  vm.cadastrando = false;
  vm.carregandoSequencias = false;
  vm.erroCatalogo = '';
  vm.mensagem = '';
  vm.mensagemTipo = '';
  vm.minhaSequencia = {};
  vm.isSearching = false;
  vm.showSearchResultsCount = false;
  vm.esfigeSpeech = "";
  vm.musics = [];
  vm.generos = GENEROS;
  vm.meuGenero = "";
  vm.progressbar = ngProgressFactory.createInstance();

  vm.temAcorde = function(acorde) {
    if (vm.minhaSequencia.acordes) {
      return (vm.minhaSequencia.acordes.indexOf(acorde) > -1);
    } else {
      return false;
    }
  };

  var limparMensagem = function() {
    vm.mensagem = '';
    vm.mensagemTipo = '';
  };

  var mostrarMensagem = function(texto, tipo) {
    vm.mensagem = texto;
    vm.mensagemTipo = tipo;
  };

  var parseAcordes = function(texto) {
    var tokens = (texto || '').split(/[\s,]+/);
    var acordes = [];
    for (var i = 0; i < tokens.length; i++) {
      if (tokens[i]) {
        acordes.push(tokens[i]);
      }
    }
    return acordes;
  };

  var encontrarSequencia = function(id) {
    for (var i = 0; i < vm.sequencias.length; i++) {
      if (vm.sequencias[i].id === id) {
        return vm.sequencias[i];
      }
    }
    return null;
  };

  var carregarSequencias = function(callback) {
    vm.carregandoSequencias = true;
    vm.erroCatalogo = '';

    $http.get('/sequencias')
      .success(function(data) {
        vm.sequencias = (data || []).map(adaptarSequencia);
        vm.carregandoSequencias = false;
        if (callback) {
          callback();
        }
      })
      .error(function() {
        vm.sequencias = [];
        vm.carregandoSequencias = false;
        vm.erroCatalogo = 'Não foi possível carregar o catálogo de sequências.';
        if (callback) {
          callback();
        }
      });
  };

  vm.carregarSequencias = carregarSequencias;

  vm.adicionarSugestao = function(acorde) {
    var texto = (vm.novaSequencia || '').replace(/\s+$/, '');
    if (texto) {
      vm.novaSequencia = texto + ', ' + acorde;
    } else {
      vm.novaSequencia = acorde;
    }
    limparMensagem();
  };

  vm.cadastrarSequencia = function() {
    var acordes = parseAcordes(vm.novaSequencia);
    limparMensagem();

    if (!acordes.length) {
      mostrarMensagem('❌ Digite ao menos um acorde.', 'danger');
      return;
    }

    vm.cadastrando = true;
    $http.post('/sequencias', { 'acordes': acordes })
      .success(function(data, status) {
        vm.cadastrando = false;
        if (status === 201) {
          mostrarMensagem('✅ Sequência cadastrada.', 'success');
        } else {
          mostrarMensagem('ℹ️ Essa sequência já existe; buscando a existente.', 'info');
        }

        vm.novaSequencia = '';
        carregarSequencias(function() {
          var sequencia = encontrarSequencia(data.id) || adaptarSequencia(data);
          vm.pesquisarPorSequencia(sequencia);
        });
      })
      .error(function(data, status) {
        vm.cadastrando = false;
        if (status === 400) {
          mostrarMensagem('❌ Sequência inválida. Informe uma lista de acordes.', 'danger');
        } else if (status === 413) {
          mostrarMensagem('❌ O conteúdo enviado é grande demais.', 'danger');
        } else if (status === 429) {
          mostrarMensagem('⏳ Limite de cadastros atingido. Tente novamente mais tarde.', 'warning');
        } else {
          mostrarMensagem('❌ Não foi possível cadastrar a sequência.', 'danger');
        }
      });
  };

  var montarUrlBusca = function() {
    if (!vm.minhaSequencia || vm.minhaSequencia.id === undefined) {
      return null;
    }

    var busca = '/similares?sequencia_id=' + encodeURIComponent(vm.minhaSequencia.id);
    if (vm.meuGenero !== "" && vm.meuGenero !== null) {
      busca += '&generos=' + encodeURIComponent(vm.meuGenero);
    }
    return busca;
  };

  vm.pesquisarPorSequencia = function(sequencia) {
    if (sequencia) {
      vm.minhaSequencia = sequencia;
    }

    var busca = montarUrlBusca();
    if (!busca) {
      vm.musics = [];
      vm.esfigeSpeech = '';
      vm.isSearching = false;
      vm.showSearchResultsCount = false;
      return;
    }

    vm.progressbar.start();
    vm.esfigeSpeech = "Procurando músicas com base na sequência...";
    vm.isSearching = true;
    vm.showSearchResultsCount = false;
    vm.musics = [];

    $http.get(busca)
      .success(function(data) {
        vm.progressbar.complete();
        vm.esfigeSpeech = "Encontrei essas músicas";
        vm.isSearching = false;
        vm.showSearchResultsCount = true;
        vm.musics = data || [];
      })
      .error(function() {
        vm.progressbar.complete();
        vm.esfigeSpeech = "Ops! Algo errado.";
        vm.isSearching = false;
        vm.showSearchResultsCount = false;
        vm.musics = [];
      });
  };

  vm.limparPesquisa = function() {
    vm.minhaSequencia = {};
    vm.musics = [];
    vm.esfigeSpeech = '';
    vm.isSearching = false;
    vm.showSearchResultsCount = false;
    limparMensagem();
  };

  vm.goToLirics = function(music) {
    $window.open(music.url);
  };

  vm.goToResults = function() {
    vm.showSearchResultsCount = false;
    $("body").animate({scrollTop: $("#results").offset().top}, "slow");
  };

  carregarSequencias();
});
